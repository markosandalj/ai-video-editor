"""Opt-in synthetic AI/PostHog probe. Writes only marked test events to PostHog.

Run with an ephemeral PostHog dependency; --run is required for network calls.
Only synthetic prompts/media and usage metadata are used. LangSmith is disabled
for this process, and all events are marked environment=validation/is_test=true.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import wave
from contextvars import ContextVar
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values
from posthog import Posthog
from posthog.ai.langchain import CallbackHandler

ROOT = Path(__file__).resolve().parents[1]
GRADIVO = ROOT.parent / "gradivo2.0"
PACKAGES = (
    "posthog",
    "langchain-core",
    "langchain-openai",
    "langchain-google-genai",
    "openai",
    "google-genai",
    "elevenlabs",
)
_receipt_properties = ContextVar("probe_receipt", default=None)


def versions():
    result = {}
    for name in PACKAGES:
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


class Probe:
    def __init__(self, output, normalized=False):
        self.gradivo = dotenv_values(GRADIVO / ".env")
        self.worker = dotenv_values(ROOT / ".env")
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        self.run_id = f"ai-validation-{datetime.now(UTC).date()}-{uuid4()}"
        self.output = output
        self.results = []
        self.delivery_errors = []
        key = self.gradivo.get("NEXT_PUBLIC_POSTHOG_KEY")
        fingerprint = 5381
        for char in key or "":
            fingerprint = ((fingerprint * 33) ^ ord(char)) & 0xFFFFFFFF
        # This public-token fingerprint was verified against project-get(33276).
        if format(fingerprint, "x") != "e3171c4e":
            raise RuntimeError("Project key differs from the verified test target")
        self.normalized = normalized
        self.client = (NormalizedPosthog if normalized else Posthog)(
            key,
            host="https://eu.i.posthog.com",
            on_error=lambda error, batch: self.delivery_errors.append(
                type(error).__name__
            ),
        )

    def properties(self, scenario, *, problem=-920001, source=-910001):
        result = {
            "environment": "validation",
            "is_test": True,
            "test_run_id": self.run_id,
            "scenario": scenario,
            "problem_source_id": source,
            "operation": "consumption_validation",
            "$process_person_profile": False,
            "$geoip_disable": True,
        }
        if problem is not None:
            result["problem_id"] = problem
        return result

    def save(self):
        self.output.write_text(
            json.dumps(
                {
                    "run_id": self.run_id,
                    "versions": versions(),
                    "results": self.results,
                    "delivery_errors": self.delivery_errors,
                },
                indent=2,
            )
        )

    def run_case(self, scenario, fn):
        try:
            result = {"scenario": scenario, "status": "succeeded", **fn()}
        except Exception as error:  # noqa: BLE001 - report each provider failure without leaking SDK bodies
            # Do not print SDK request objects, credentials, URLs or response bodies.
            result = {
                "scenario": scenario,
                "status": "failed",
                "error_type": type(error).__name__,
                "http_status": getattr(error, "status_code", None),
            }
            details = str(getattr(error, "message", ""))[:600]
            for values in (self.gradivo, self.worker):
                for key, value in values.items():
                    if value and any(
                        part in key for part in ("KEY", "TOKEN", "SECRET")
                    ):
                        details = details.replace(value, "[REDACTED]")
            result["error_message"] = details
        self.results.append(result)
        self.save()
        print(json.dumps(result), flush=True)

    def llm(
        self,
        provider,
        scenario,
        *,
        asynchronous=False,
        problem=-920001,
        source=-910001,
        audio=False,
    ):
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_openai import ChatOpenAI

        raw = []

        def retain(response):
            payload = response.json()
            raw.append(
                {
                    "status": response.status_code,
                    "request_id": payload.get("id") or payload.get("responseId"),
                    "model": payload.get("model") or payload.get("modelVersion"),
                    "usage": payload.get("usage") or payload.get("usageMetadata"),
                }
            )

        def response_hook(response):
            response.read()
            retain(response)

        async def async_response_hook(response):
            await response.aread()
            retain(response)

        sync = httpx.Client(event_hooks={"response": [response_hook]})
        async_client = httpx.AsyncClient(
            event_hooks={"response": [async_response_hook]}
        )
        if provider == "google":
            model = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                api_key=self.gradivo["GEMINI_API_KEY"],
                max_output_tokens=256,
                thinking_budget=128,
                temperature=0,
                max_retries=0,
                timeout=45,
                disable_streaming=True,
                client_args={"transport": UsageTransport(retain)},
            )
        else:
            options = {
                "model": "gpt-5-mini",
                "api_key": self.gradivo["OPENAI_API_KEY"],
                "max_tokens": 256,
                "reasoning_effort": "minimal",
            }
            if provider == "openrouter":
                from ai_video_editor.llm import default_section_editor_model_config

                config = default_section_editor_model_config()
                options = {
                    "model": config.model,
                    "api_key": self.worker["OPENROUTER_API_KEY"],
                    **config.provider_kwargs,
                    "max_tokens": 256,
                }
            options.update(
                max_retries=0,
                timeout=45,
                disable_streaming=True,
                http_client=sync,
                http_async_client=async_client,
            )
            model = ChatOpenAI(**options)
        trace_id = str(uuid4())
        handler = (ProviderReceiptCallback if self.normalized else CallbackHandler)(
            client=self.client,
            distinct_id=f"{self.run_id}:user",
            trace_id=trace_id,
            privacy_mode=True,
            properties=self.properties(scenario, problem=problem, source=source),
        )
        handler.raise_error = True
        config = {"callbacks": [handler], "run_name": scenario}
        message = "Return only OK."
        if audio:
            with self.audio() as stream:
                encoded = base64.b64encode(stream.read()).decode()
            message = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Listen to this audio and return only OK.",
                        },
                        {"type": "media", "mime_type": "audio/wav", "data": encoded},
                    ],
                }
            ]
        if asynchronous:

            async def invoke():
                try:
                    return await model.ainvoke(message, config=config)
                finally:
                    await async_client.aclose()

            response = asyncio.run(invoke())
        else:
            response = model.invoke(message, config=config)
            asyncio.run(async_client.aclose())
        sync.close()
        return {
            "provider": provider,
            "trace_id": trace_id,
            "raw_receipts": raw,
            "sdk_usage": response.usage_metadata,
            "sdk_token_usage": response.response_metadata.get("token_usage"),
            "sdk_model": response.response_metadata.get("model_name"),
            "problem_source_id": source,
            "problem_id": problem,
        }

    def resource(
        self, scenario, provider, model, usage, *, receipt=None, cost=None, tokens=False
    ):
        props = {
            **self.properties(scenario, problem=None),
            "provider": provider,
            "model": model,
            "resource_usage": usage,
            "cost_basis": "unavailable",
        }
        if receipt:
            props["provider_request_id"] = receipt
        if cost is not None:
            unit, amount = cost["unit"], cost["amount"]
            if unit == "DOLLARS":
                props.update(cost_basis="charged", charged_cost_usd=float(amount))
            elif unit == "CREDITS":
                props["resource_usage"] = {**usage, "credits": float(amount)}
        event = "production_ai_resource_validation"
        if tokens:
            event = "$ai_generation"
            props.update(
                {
                    "$ai_provider": provider,
                    "$ai_model": model,
                    "$ai_trace_id": str(uuid4()),
                    "$ai_input_tokens": usage.get("input_tokens"),
                    "$ai_output_tokens": usage.get("output_tokens"),
                }
            )
        identity = uuid4()
        if not self.client.capture(
            event=event,
            distinct_id=f"{self.run_id}:user",
            uuid=identity,
            properties=props,
        ):
            raise RuntimeError("SDK capture rejected")
        return {
            "event_uuid": str(identity),
            "usage": usage,
            "cost": cost,
            "captured_properties": props,
        }

    def audio(self):
        data = io.BytesIO()
        with wave.open(data, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\0\0" * 16000 * 3)
        data.seek(0)
        data.name = "validation-silence.wav"
        return data

    def whisper(self):
        from openai import OpenAI

        client = OpenAI(
            api_key=self.gradivo["OPENAI_API_KEY"], max_retries=0, timeout=45
        )
        with self.audio() as audio:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio,
                response_format="verbose_json",
                language="en",
            )
        client.close()
        return self.resource(
            "whisper_audio",
            "openai",
            "whisper-1",
            {"submitted_audio_seconds": 3, "provider_audio_seconds": result.duration},
        )

    def elevenlabs(self):
        from elevenlabs import ElevenLabs

        client = ElevenLabs(api_key=self.worker["ELEVENLABS_API_KEY"], timeout=45)
        with self.audio() as audio:
            result = client.speech_to_text.convert(
                model_id="scribe_v2",
                file=audio,
                language_code="en",
                tag_audio_events=False,
                request_options={"max_retries": 0},
            )
        payload = result.model_dump()
        return {
            "response_fields": sorted(payload),
            **self.resource(
                "elevenlabs_audio",
                "elevenlabs",
                "scribe_v2",
                {"audio_seconds": 3},
                receipt=payload.get("transcription_id"),
            ),
        }

    def jev(self):
        model = self.gradivo.get("JEV_MODEL") or "jev-1.13.0"
        result = httpx.post(
            "https://api.typesafe.ai/v1/systemone",
            headers={"Authorization": f"Bearer {self.gradivo['JEV_API_KEY']}"},
            json={
                "model": model,
                "state": {"problem_text": "Calculate 1 + 1."},
                "questions": {
                    "subject": {
                        "type": "choice",
                        "instructions": "Choose the subject.",
                        "criteria": {"math": "Mathematics", "history": "History"},
                    }
                },
            },
            timeout=45,
        )
        result.raise_for_status()
        payload = result.json()
        return self.resource(
            "jev_usage",
            "jev",
            payload.get("model", model),
            payload.get("usage", {}),
            receipt=payload.get("id"),
            tokens=True,
        )

    def image_bytes(self):
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (512, 256), "white")
        ImageDraw.Draw(image).text(
            (60, 80), "1 + 1 = 2", fill="black", font=ImageFont.load_default(size=50)
        )
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()

    def mathpix(self):
        response = httpx.post(
            "https://api.mathpix.com/v3/text",
            headers={
                "app_id": self.gradivo["MATHPIX_APP_ID"],
                "app_key": self.gradivo["MATHPIX_APP_KEY"],
            },
            json={
                "src": f"data:image/png;base64,{self.image_bytes()}",
                "formats": ["text"],
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error") or payload.get("error_info"):
            raise RuntimeError("OCR provider returned an error")
        return {
            "response_fields": sorted(payload),
            **self.resource(
                "mathpix_image",
                "mathpix",
                "text",
                {"images": 1},
                receipt=payload.get("request_id"),
            ),
        }

    def leonardo(self):
        response = httpx.post(
            "https://cloud.leonardo.ai/api/rest/v2/generationssync",
            headers={"Authorization": f"Bearer {self.gradivo['LEONARDO_API_KEY']}"},
            json={
                "model": "remove-bg",
                "public": False,
                "ephemeral": True,
                "parameters": {
                    "size": "full",
                    "format": "png",
                    "guidances": {
                        "image_reference": [
                            {"image": {"type": "BASE64", "data": self.image_bytes()}}
                        ]
                    },
                },
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return {
                "status": "rejected",
                "provider_status": "rejected",
                "errors": [
                    {
                        "message": item.get("message", "")[:400],
                        "extensions": item.get("extensions", {}),
                    }
                    for item in payload
                    if isinstance(item, dict)
                ],
            }
        payload = payload.get("generateSync", payload)
        if payload.get("error") or payload.get("errors"):
            raise RuntimeError("Image provider returned an error")
        return {
            "response_fields": sorted(payload),
            **self.resource(
                "leonardo_image",
                "leonardo",
                "remove-bg",
                {"images": 1},
                receipt=payload.get("id"),
                cost=payload.get("cost"),
            ),
        }

    def finish(self):
        self.client.flush()
        self.client.shutdown()
        self.save()
        if self.delivery_errors:
            raise RuntimeError("PostHog delivery failed; see non-sensitive evidence")


class UsageTransport(httpx.BaseTransport, httpx.AsyncBaseTransport):
    """Test observer only: preserve provider usage, never request/response content."""

    def __init__(self, retain):
        self.retain = retain
        self.sync = httpx.HTTPTransport()
        self.asynchronous = httpx.AsyncHTTPTransport()

    def handle_request(self, request):
        response = self.sync.handle_request(request)
        response.read()
        self.retain(response)
        return response

    async def handle_async_request(self, request):
        response = await self.asynchronous.handle_async_request(request)
        await response.aread()
        self.retain(response)
        return response

    def close(self):
        self.sync.close()

    async def aclose(self):
        await self.asynchronous.aclose()


class NormalizedPosthog(Posthog):
    """Candidate adapter tested here, not wired into the application."""

    def capture(self, event, **kwargs):
        props = dict(kwargs.get("properties") or {})
        if event == "$ai_generation":
            props.update(_receipt_properties.get() or {})
        if event == "$ai_generation" and props.get("$ai_provider") == "google_genai":
            # LangChain output already includes thinking. Preserve the subtype in
            # a custom field so ingestion does not add it to the price a second time.
            props["reasoning_tokens"] = props.pop("$ai_reasoning_tokens", 0)
            props["output_tokens_include_reasoning"] = True
        kwargs["properties"] = props
        return super().capture(event, **kwargs)


class ProviderReceiptCallback(CallbackHandler):
    def on_llm_end(self, response, *, run_id, **kwargs):
        usage = (response.llm_output or {}).get("token_usage") or {}
        properties = (
            {"provider_billed_cost_usd": usage["cost"], "cost_basis": "charged"}
            if usage.get("cost") is not None
            else {}
        )
        token = _receipt_properties.set(properties)
        try:
            super().on_llm_end(response, run_id=run_id, **kwargs)
        finally:
            _receipt_properties.reset(token)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument(
        "--group",
        choices=(
            "llm",
            "resources",
            "corrections",
            "whisper",
            "images",
            "openrouter",
            "final",
        ),
        default="llm",
    )
    parser.add_argument("--normalized", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({"versions": versions(), "network_enabled": args.run}), flush=True)
    if not args.run:
        return
    probe = Probe(args.output, normalized=args.normalized)
    print(json.dumps({"run_id": probe.run_id}), flush=True)
    try:
        if args.group == "llm":
            probe.run_case("openai_1", lambda: probe.llm("openai", "openai_1"))
            probe.run_case("openai_2", lambda: probe.llm("openai", "openai_2"))
            probe.run_case(
                "gemini_async",
                lambda: probe.llm(
                    "google", "gemini_async", asynchronous=True, problem=-920002
                ),
            )
            probe.run_case(
                "openrouter",
                lambda: probe.llm(
                    "openrouter", "openrouter", source=-910002, problem=None
                ),
            )
        elif args.group == "resources":
            probe.run_case("whisper_audio", probe.whisper)
            probe.run_case("elevenlabs_audio", probe.elevenlabs)
            probe.run_case("jev_usage", probe.jev)
        elif args.group == "whisper":
            probe.run_case("whisper_audio", probe.whisper)
        elif args.group == "images":
            probe.run_case("mathpix_image", probe.mathpix)
            probe.run_case("leonardo_image", probe.leonardo)
        elif args.group == "openrouter":
            probe.run_case(
                "openrouter_billed",
                lambda: probe.llm(
                    "openrouter", "openrouter_billed", source=-910002, problem=None
                ),
            )
        elif args.group == "final":
            probe.run_case(
                "gemini_audio", lambda: probe.llm("google", "gemini_audio", audio=True)
            )
            probe.run_case("leonardo_image", probe.leonardo)
        else:
            probe.run_case(
                "gemini_normalized",
                lambda: probe.llm(
                    "google", "gemini_normalized", asynchronous=True, problem=-920002
                ),
            )
            probe.run_case(
                "openrouter_billed",
                lambda: probe.llm(
                    "openrouter", "openrouter_billed", source=-910002, problem=None
                ),
            )
    finally:
        probe.finish()
    if any(result["status"] != "succeeded" for result in probe.results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

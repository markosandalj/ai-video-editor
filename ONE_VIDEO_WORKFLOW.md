# One Video Workflow

This document explains what happens to one raw recording as it moves through the AI video editor, from the original input file to the final reviewed output.

It is written for people who need to understand the process, not the implementation details.

## Short Version

One raw video goes through three main stages:

1. The system prepares the recording so it can understand the speech and timing.
2. The system proposes an edited version by cutting silence, repeated takes, false starts, and other likely mistakes.
3. A person reviews the proposed edit, fixes anything the system got wrong, and produces the final reviewed video.

The important rule is that the system should never destroy the original recording. The raw video stays available, the automatic edit is saved separately, and the reviewed edit is saved separately again.

## Starting Point: Raw Input

The process starts with one raw screen recording. In the Gradivo content workflow, this should normally mean one raw explanation video for one problem.

The raw video may contain:

- long pauses while the professor writes or thinks
- background noise
- repeated explanations
- false starts
- coughs, interruptions, or short non-lesson comments
- moments where the professor corrects themselves

The goal is not to make a flashy edited video. The goal is to remove obvious recording friction while preserving the lesson and the professor's natural flow.

## Stage 1: Preparing The Recording

First, the system prepares the raw file for analysis.

It extracts the audio from the video, because most editing decisions are based on speech and sound. The video picture is still kept, but the system needs a clean audio track to understand where speech happens and where mistakes may be.

The system then reduces steady background noise. This is meant to make speech easier to analyze and to improve the final audio. It should not change the meaning of the lesson or remove spoken words.

Next, the system looks for long silent parts. A short pause can sound natural, so short pauses are kept. Longer silent parts can usually be shortened. The system adds a small safety margin around speech so the beginning and end of words are not cut too tightly.

At the end of this stage, the system has a cleaner audio track and a rough idea of which parts of the recording contain useful speech.

## Stage 2: Turning Speech Into Reviewable Text

The system transcribes the recording. This means it turns the spoken Croatian explanation into written text with timing information.

The timing matters because the system does not only need to know what was said. It also needs to know when each sentence and word happened in the original video.

After transcription, the system lightly corrects the written transcript so it is easier to analyze. This correction is used for editing decisions and review. It is not the final student-facing transcript for Gradivo publishing.

The transcript is split into sentence-sized pieces. This makes the later review practical: instead of asking a reviewer to inspect one long wall of text, the system can show one sentence or small segment at a time.

## Stage 3: Finding Likely Cuts

The system now tries to decide which parts of the video should stay and which parts should be removed.

It looks for several types of material:

- long silence that slows down the lesson
- repeated takes where the professor says the same thing again
- false starts where the professor begins a thought and immediately restarts it
- stutters or repeated fragments inside a sentence
- short side comments that are probably not part of the lesson
- audio disruptions such as coughs or noises around a restart

The system combines sound evidence and transcript evidence. For example, a repeated sentence is easier to detect from text, while a cough or disruption is easier to detect from audio.

The system also runs an enrichment pass. This is a second opinion over the transcript. It scores sentences, marks items that deserve attention, and can warn when something the automatic edit planned to cut may actually be important.

The result is an automatic edit plan. This plan says which parts of the original video should be kept, which parts should be cut, and why.

## Stage 4: Automatic Edited Video

Using the automatic edit plan, the system renders an automatically edited video.

This video is a first draft. It uses the original video picture, the cleaned audio, and the proposed keep/cut decisions. Small fades are added around cut points so the audio transitions are less harsh.

This automatic video is useful because it gives reviewers something close to the expected final result. But it is not treated as final by default.

The original raw video is still kept. The automatic edit plan is also kept, so the system can explain what it did and the reviewer can change the decisions later.

## Stage 5: Human Review

The automatic edit is opened in the review interface.

The reviewer can inspect the transcript and video together. The review interface shows which parts the system wants to keep, which parts it wants to cut, and which parts need attention.

The reviewer checks whether the automatic edit preserved the actual lesson. They are looking for problems such as:

- a useful explanation was cut
- a bad take was kept
- a pause was shortened too aggressively
- a natural transition sounds awkward after a cut
- the transcript review marker suggests uncertainty

The reviewer can change keep/cut decisions. These corrections are saved separately from the automatic edit. This matters because we can always compare the original automatic choice with the human-reviewed choice.

## Stage 6: Final Reviewed Output

After review, the system renders a reviewed video from the reviewed decisions.

This final reviewed output is the result of the AI proposal plus human correction. It should be the version that is ready for the next production step.

The final reviewed video does not overwrite the raw recording and does not overwrite the first automatic edit. The process keeps the important layers separate:

- the original raw recording
- the automatic transcript and analysis
- the automatic edit plan
- the automatic edited video
- the human-reviewed edit plan
- the final reviewed video

This separation keeps the workflow safer. If a mistake is found later, the team can inspect what happened, restore material from the raw recording, or rerun parts of the process.

## What Happens After The Reviewed Output

The AI video editor's job ends when it has produced the final reviewed video and the review decisions behind it.

In the larger Gradivo workflow, the reviewed video still needs to be handled by Gradivo's production process. That includes upload to the final video platform, final transcription, chapters, explanations, review, and publishing.

The transcript created by the AI video editor is currently an internal editing aid. Gradivo should still create the student-facing transcript from the final reviewed video, because that transcript must match exactly what students will watch.

## What This Process Currently Does Not Cover

This process currently does not cover every future production feature.

It does not finalize student-facing publishing by itself. It does not replace Gradivo's video model, Mux upload, chapters, explanations, or publishability checks.

It also does not currently add intro or outro screens. The focus is on cleaning and reviewing the explanation itself.

Production render settings still need final validation on representative videos before this can be treated as a fully production-ready service.

## The Core Principle

The system should make the first edit faster, not make the final decision alone.

The AI editor removes obvious friction and highlights uncertain spots. A human reviewer confirms the final lesson. The final reviewed output should be faster to produce than a manual edit, while still preserving human control over educational correctness.

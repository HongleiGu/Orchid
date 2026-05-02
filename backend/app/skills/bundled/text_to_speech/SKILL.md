---
name: text_to_speech
description: Convert text to speech audio. Returns a playable audio file as a base64 data URL. Best for short to medium-length text (under 4000 characters).
timeout: 90
parameters:
  type: object
  properties:
    text:
      type: string
      description: The text to convert to speech.
    voice:
      type: string
      enum: [alloy, echo, fable, onyx, nova, shimmer]
      default: nova
    speed:
      type: number
      default: 1.0
      description: Playback speed (0.25 to 4.0).
  required: [text]
---

Uses OpenAI tts-1. Returns a JSON content block: {"type":"audio","url":"data:audio/mp3;base64,...","format":"mp3"}.

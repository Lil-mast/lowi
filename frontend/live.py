"""Streamlit live-capture component (Custom Components v2)."""

from __future__ import annotations

import streamlit as st

_HTML = """
<div id="lowi-live" class="lowi-live">
  <div class="lowi-row">
    <label for="lowi-source">Source</label>
    <select id="lowi-source">
      <option value="mic">Microphone</option>
      <option value="tab">Shared tab audio</option>
    </select>
    <button id="lowi-start" type="button">Start recording</button>
    <button id="lowi-stop" type="button" disabled>Stop</button>
  </div>
  <p id="lowi-status" data-state="idle">Choose a source and start recording.</p>
  <div class="lowi-panels">
    <section>
      <h4>Live</h4>
      <p id="lowi-partial" class="lowi-partial"></p>
    </section>
    <section>
      <h4>Committed</h4>
      <p id="lowi-final" class="lowi-final"></p>
    </section>
  </div>
  <p class="lowi-hint">
    For a meeting tab, choose <strong>Share tab audio</strong> in the browser picker.
    Keep this tab open. The final batch transcript with speaker labels is produced after you stop.
  </p>
</div>
"""

_CSS = """
.lowi-live {
  font-family: var(--st-font, sans-serif);
  color: var(--st-text-color, #202124);
  border: 1px solid var(--st-border-color, #d6d6d6);
  border-radius: 0.75rem;
  padding: 1rem;
  background: var(--st-secondary-background-color, #f7f7f7);
}
.lowi-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem;
}
.lowi-row label {
  font-size: 0.9rem;
  color: var(--st-text-color, #202124);
}
.lowi-row select,
.lowi-row button {
  font: inherit;
  border-radius: 0.45rem;
  border: 1px solid var(--st-border-color, #c7c7c7);
  padding: 0.45rem 0.7rem;
  background: var(--st-background-color, #fff);
  color: var(--st-text-color, #202124);
}
.lowi-row button {
  cursor: pointer;
  font-weight: 600;
}
.lowi-row button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
#lowi-start:not(:disabled) {
  background: var(--st-primary-color, #ff4b4b);
  border-color: var(--st-primary-color, #ff4b4b);
  color: var(--st-primary-text-color, #fff);
}
#lowi-status {
  margin: 0.8rem 0 0.6rem;
  font-size: 0.9rem;
  min-height: 1.4rem;
}
#lowi-status[data-state="live"] { color: var(--st-green-color, #1a7f37); }
#lowi-status[data-state="busy"] { color: var(--st-yellow-color, #9a6700); }
#lowi-status[data-state="error"] { color: var(--st-red-color, #cf222e); }
#lowi-status[data-state="ok"] { color: var(--st-green-color, #1a7f37); }
.lowi-panels {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.75rem;
}
.lowi-panels section {
  min-height: 8rem;
  max-height: 12rem;
  overflow-y: auto;
  border: 1px solid var(--st-border-color, #d6d6d6);
  border-radius: 0.6rem;
  padding: 0.7rem;
  background: var(--st-background-color, #fff);
}
.lowi-panels h4 {
  margin: 0 0 0.4rem;
  font-size: 0.75rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--st-gray-text-color, #666);
}
.lowi-partial, .lowi-final {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.45;
  font-size: 0.95rem;
}
.lowi-partial { color: var(--st-gray-text-color, #666); }
.lowi-hint {
  margin: 0.8rem 0 0;
  font-size: 0.78rem;
  line-height: 1.4;
  color: var(--st-gray-text-color, #666);
}
"""

_JS = """
export default function (component) {
  const { data, parentElement, setTriggerValue } = component
  const root = parentElement.querySelector("#lowi-live")
  if (!root) return

  const source = root.querySelector("#lowi-source")
  const startButton = root.querySelector("#lowi-start")
  const stopButton = root.querySelector("#lowi-stop")
  const status = root.querySelector("#lowi-status")
  const partial = root.querySelector("#lowi-partial")
  const final = root.querySelector("#lowi-final")

  if (!root.__lowiLive) {
    root.__lowiLive = {
      ws: null,
      stream: null,
      ctx: null,
      running: false,
      stopping: false,
      finished: false,
      finalText: "",
    }
  }
  const state = root.__lowiLive
  const initial = (data && data.initialTranscript) || ""
  if (!state.running && !state.finished && initial) {
    state.finalText = initial
    final.textContent = initial
  }

  function setStatus(text, kind) {
    status.textContent = text
    status.dataset.state = kind || "idle"
  }

  function stopCapture() {
    if (state.stream) {
      state.stream.getTracks().forEach((track) => track.stop())
      state.stream = null
    }
    if (state.ctx) {
      state.ctx.close().catch(() => {})
      state.ctx = null
    }
  }

  function resetButtons() {
    startButton.disabled = false
    stopButton.disabled = true
    source.disabled = false
  }

  function finish(failed) {
    if (state.finished) return
    state.finished = true
    state.running = false
    state.stopping = false
    stopCapture()
    if (state.ws) {
      try { state.ws.close() } catch (_) {}
      state.ws = null
    }
    if (failed) {
      setStatus("Recording ended with an error. The saved part may still be processed.", "error")
    } else {
      setStatus("Recording complete. Batch diarization and the summary are queued.", "ok")
    }
    resetButtons()
    setTriggerValue("stopped", {
      transcript: state.finalText || "",
      failed: Boolean(failed),
      at: Date.now(),
    })
  }

  function downsample(buffer, inputRate, outputRate) {
    if (inputRate === outputRate) return buffer
    const ratio = inputRate / outputRate
    const length = Math.round(buffer.length / ratio)
    const result = new Float32Array(length)
    for (let i = 0; i < length; i += 1) {
      const start = Math.round(i * ratio)
      const end = Math.min(Math.round((i + 1) * ratio), buffer.length)
      let sum = 0
      for (let j = start; j < end; j += 1) sum += buffer[j]
      result[i] = sum / Math.max(1, end - start)
    }
    return result
  }

  function toPcm16(buffer) {
    const output = new Int16Array(buffer.length)
    for (let i = 0; i < buffer.length; i += 1) {
      const sample = Math.max(-1, Math.min(1, buffer[i]))
      output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
    }
    return output
  }

  function stop() {
    if (!state.running || state.stopping) return
    state.stopping = true
    stopButton.disabled = true
    setStatus("Finishing the live transcript…", "busy")
    stopCapture()
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({ type: "stop" }))
    } else {
      finish(true)
    }
  }

  async function begin() {
    if (state.running || state.stopping) return
    const selected = source.value
    startButton.disabled = true
    stopButton.disabled = false
    source.disabled = true
    setStatus("Requesting audio access…", "busy")

    try {
      let stream
      if (selected === "tab") {
        stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true })
        if (!stream.getAudioTracks().length) {
          stream.getTracks().forEach((track) => track.stop())
          throw new Error("No tab audio was shared. Pick a tab and turn on Share tab audio.")
        }
      } else {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        })
      }

      const ws = new WebSocket(data.wsUrl + "&source=" + encodeURIComponent(selected))
      ws.binaryType = "arraybuffer"
      state.ws = ws
      state.stream = stream
      state.running = true
      state.stopping = false
      state.finished = false
      state.finalText = ""
      partial.textContent = ""
      final.textContent = ""
      setStatus("Connecting to the transcription service…", "busy")

      const audioTrack = stream.getAudioTracks()[0]
      if (audioTrack) {
        audioTrack.onended = () => {
          if (state.running) stop()
        }
      }

      ws.onopen = () => setStatus("Recording…", "live")
      ws.onmessage = (event) => {
        let message
        try { message = JSON.parse(event.data) } catch (_) { return }
        if (message.type === "ready" || message.type === "upstream_ready") {
          setStatus("Recording…", "live")
        } else if (message.type === "partial") {
          partial.textContent = message.text || ""
        } else if (message.type === "final") {
          if (message.text) {
            state.finalText = (state.finalText ? state.finalText + " " : "") + message.text
            final.textContent = state.finalText
          }
          partial.textContent = ""
        } else if (message.type === "finalizing") {
          setStatus("Saving the recording and queueing diarization…", "busy")
        } else if (message.type === "error") {
          setStatus(message.message || "Live transcription failed.", "error")
        } else if (message.type === "stopped") {
          finish(false)
        }
      }
      ws.onerror = () => setStatus("Connection error. Check the API URL and try again.", "error")
      ws.onclose = () => {
        if (state.finished) return
        if (state.stopping) {
          setStatus("The connection closed while saving.", "error")
          finish(true)
        } else {
          setStatus("The transcription connection closed.", "error")
          finish(true)
        }
      }

      const ctx = new AudioContext()
      if (ctx.state === "suspended") await ctx.resume()
      const sourceNode = ctx.createMediaStreamSource(stream)
      const processor = ctx.createScriptProcessor(4096, 1, 1)
      const mute = ctx.createGain()
      mute.gain.value = 0
      processor.onaudioprocess = (event) => {
        if (!state.running || !state.ws || state.ws.readyState !== WebSocket.OPEN) return
        const input = event.inputBuffer.getChannelData(0)
        const downsampled = downsample(input, ctx.sampleRate, 16000)
        state.ws.send(toPcm16(downsampled).buffer)
      }
      sourceNode.connect(processor)
      processor.connect(mute)
      mute.connect(ctx.destination)
      state.ctx = ctx
    } catch (error) {
      setStatus(error.message || "Could not access audio.", "error")
      state.running = false
      state.stopping = false
      stopCapture()
      if (state.ws) {
        try { state.ws.close() } catch (_) {}
        state.ws = null
      }
      resetButtons()
    }
  }

  startButton.onclick = begin
  stopButton.onclick = stop

  return () => {
    if (state.running || state.stopping) {
      try {
        if (state.ws && state.ws.readyState === WebSocket.OPEN) {
          state.ws.send(JSON.stringify({ type: "stop" }))
        }
      } catch (_) {}
    }
    stopCapture()
    if (state.ws) {
      try { state.ws.close() } catch (_) {}
      state.ws = null
    }
  }
}
"""

_LIVE_COMPONENT = None


def _component():
    global _LIVE_COMPONENT
    if _LIVE_COMPONENT is None:
        _LIVE_COMPONENT = st.components.v2.component(
            "lowi_live_capture",
            html=_HTML,
            css=_CSS,
            js=_JS,
        )
    return _LIVE_COMPONENT


def render_live_capture(
    *,
    ws_url: str,
    initial_transcript: str = "",
    key: str,
):
    return _component()(
        key=key,
        data={"wsUrl": ws_url, "initialTranscript": initial_transcript},
        height=360,
        on_stopped_change=lambda: None,
    )

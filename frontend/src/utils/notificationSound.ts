/**
 * Web Audio API chime synthesizer & mobile device vibration utility for WayMate.
 * Synthesizes crisp notification tones without external audio file dependencies.
 */

class NotificationFeedbackService {
  private audioCtx: AudioContext | null = null

  private getAudioContext(): AudioContext | null {
    if (typeof window === "undefined") return null
    try {
      if (!this.audioCtx) {
        const AudioCtxClass = window.AudioContext || (window as any).webkitAudioContext
        if (AudioCtxClass) {
          this.audioCtx = new AudioCtxClass()
        }
      }
      if (this.audioCtx && this.audioCtx.state === "suspended") {
        this.audioCtx.resume().catch(() => {})
      }
      return this.audioCtx
    } catch {
      return null
    }
  }

  /**
   * Plays a pleasant multi-tone chime and vibrates supported mobile devices.
   */
  playNotificationSound(type: "request" | "accepted" | "match" | "default" = "default") {
    // 1. Device Vibration (supported Android & mobile browsers)
    try {
      if (typeof window !== "undefined" && "navigator" in window && "vibrate" in navigator) {
        if (type === "accepted") {
          navigator.vibrate([120, 80, 220])
        } else if (type === "request" || type === "match") {
          navigator.vibrate([250, 100, 250, 100, 250])
        } else {
          navigator.vibrate([160])
        }
      }
    } catch {
      // Ignore vibration errors if restricted by device/browser
    }

    // 2. Synthesize audio chime via Web Audio API
    try {
      const ctx = this.getAudioContext()
      if (!ctx) return

      const now = ctx.currentTime

      if (type === "accepted") {
        // Celebratory major triad chime (C5 -> E5 -> G5)
        this.playTone(ctx, 523.25, now, 0.12, 0.28)        // C5
        this.playTone(ctx, 659.25, now + 0.10, 0.12, 0.28)  // E5
        this.playTone(ctx, 783.99, now + 0.20, 0.35, 0.32)  // G5
      } else if (type === "request" || type === "match") {
        // High-attention modern two-tone chime (F#5 -> B5)
        this.playTone(ctx, 739.99, now, 0.14, 0.30)         // F#5
        this.playTone(ctx, 987.77, now + 0.12, 0.40, 0.34)  // B5
      } else {
        // Gentle single-tone chime (A5)
        this.playTone(ctx, 880.00, now, 0.22, 0.25)         // A5
      }
    } catch {
      // Audio autoplay may be restrained until user interacts with document
    }
  }

  /**
   * Unlocks the AudioContext on first user gesture without playing sound.
   */
  unlock() {
    const ctx = this.getAudioContext()
    if (ctx && ctx.state === "suspended") {
      ctx.resume().catch(() => {})
    }
  }

  private playTone(ctx: AudioContext, freq: number, startTime: number, duration: number, peakGain: number = 0.25) {
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()

    osc.type = "sine"
    osc.frequency.setValueAtTime(freq, startTime)

    // Smooth envelope attack and decay to prevent clicking
    gain.gain.setValueAtTime(0, startTime)
    gain.gain.linearRampToValueAtTime(peakGain, startTime + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.0001, startTime + duration)

    osc.connect(gain)
    gain.connect(ctx.destination)

    osc.start(startTime)
    osc.stop(startTime + duration)
  }
}

export const notificationFeedback = new NotificationFeedbackService()

// Attach document listener to unlock AudioContext on first user gesture
if (typeof window !== "undefined") {
  const unlockAudio = () => {
    notificationFeedback.unlock()
    window.removeEventListener("pointerdown", unlockAudio)
    window.removeEventListener("keydown", unlockAudio)
  }
  window.addEventListener("pointerdown", unlockAudio, { once: true, passive: true })
  window.addEventListener("keydown", unlockAudio, { once: true, passive: true })
}

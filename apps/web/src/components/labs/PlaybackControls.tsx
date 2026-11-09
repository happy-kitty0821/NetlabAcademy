"use client";

/**
 * PlaybackControls — play/pause/step/reset + speed slider for
 * replaying the simulation trace.
 */

import { Button } from "@/components/ui/Button";
import { Pause, Play, SkipForward, RotateCcw } from "lucide-react";

interface PlaybackControlsProps {
  isPlaying: boolean;
  onPlay: () => void;
  onPause: () => void;
  onStep: () => void;
  onReset: () => void;
  currentStep: number;
  totalSteps: number;
  speed: number;
  onSpeedChange: (speed: number) => void;
  disabled?: boolean;
}

export function PlaybackControls({
  isPlaying,
  onPlay,
  onPause,
  onStep,
  onReset,
  currentStep,
  totalSteps,
  speed,
  onSpeedChange,
  disabled,
}: PlaybackControlsProps) {
  const progress = totalSteps > 0 ? (currentStep / totalSteps) * 100 : 0;

  return (
    <div className="flex items-center gap-3 flex-wrap">
      {/* Play / Pause */}
      {isPlaying ? (
        <Button size="sm" variant="secondary" onClick={onPause} disabled={disabled}>
          <Pause size={13} aria-hidden="true" />
          Pause
        </Button>
      ) : (
        <Button size="sm" onClick={onPlay} disabled={disabled || currentStep >= totalSteps}>
          <Play size={13} aria-hidden="true" />
          Play
        </Button>
      )}

      {/* Step forward */}
      <Button
        size="sm"
        variant="ghost"
        onClick={onStep}
        disabled={disabled || isPlaying || currentStep >= totalSteps}
      >
        <SkipForward size={13} aria-hidden="true" />
        Step
      </Button>

      {/* Reset */}
      <Button
        size="sm"
        variant="ghost"
        onClick={onReset}
        disabled={disabled || currentStep === 0}
      >
        <RotateCcw size={13} aria-hidden="true" />
        Reset
      </Button>

      {/* Progress */}
      <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)] font-mono min-w-[80px]">
        <span>
          {currentStep}/{totalSteps}
        </span>
      </div>

      {/* Progress bar */}
      <div className="flex-1 min-w-[60px] h-1.5 rounded-full bg-[var(--surface-overlay)] overflow-hidden">
        <div
          className="h-full bg-[var(--accent-primary)] transition-all duration-200"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Speed control */}
      <div className="flex items-center gap-1.5">
        <span className="text-xs text-[var(--text-muted)]">Speed</span>
        <input
          type="range"
          min="200"
          max="2000"
          step="100"
          value={2200 - speed}
          onChange={(e) => onSpeedChange(2200 - parseInt(e.target.value))}
          disabled={disabled}
          className="w-20 accent-[var(--accent-primary)]"
          aria-label="Playback speed"
        />
        <span className="text-xs text-[var(--text-muted)] font-mono w-12">
          {(1000 / speed).toFixed(1)}x
        </span>
      </div>
    </div>
  );
}

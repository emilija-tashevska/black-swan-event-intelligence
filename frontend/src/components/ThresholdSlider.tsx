"use client";

interface ThresholdSliderProps {
  value: number;
  onChange: (val: number) => void;
  steps?: number[];
}

export default function ThresholdSlider({ value, onChange, steps }: ThresholdSliderProps) {
  if (steps) {
    const idx = steps.reduce((best, curr, i) =>
      Math.abs(curr - value) < Math.abs(steps[best] - value) ? i : best, 0);
    return (
      <div className="flex items-center gap-4">
        <label htmlFor="threshold" className="text-sm font-medium text-muted-foreground whitespace-nowrap">
          Threshold
        </label>
        <input
          id="threshold"
          type="range"
          min={0}
          max={steps.length - 1}
          step={1}
          value={idx}
          onChange={(e) => onChange(steps[parseInt(e.target.value)])}
          className="w-40 h-1.5 bg-muted rounded-lg appearance-none cursor-pointer accent-accent"
        />
        <span className="text-sm font-semibold tabular-nums text-accent min-w-[3.5rem] text-right">
          {(value * 100).toFixed(0)}%
        </span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-4">
      <label htmlFor="threshold" className="text-sm font-medium text-muted-foreground whitespace-nowrap">
        Threshold
      </label>
      <input
        id="threshold"
        type="range"
        min={1}
        max={25}
        step={1}
        value={Math.round(value * 100)}
        onChange={(e) => onChange(parseInt(e.target.value) / 100)}
        className="w-40 h-1.5 bg-muted rounded-lg appearance-none cursor-pointer accent-accent"
      />
      <span className="text-sm font-semibold tabular-nums text-accent min-w-[3.5rem] text-right">
        {(value * 100).toFixed(0)}%
      </span>
    </div>
  );
}

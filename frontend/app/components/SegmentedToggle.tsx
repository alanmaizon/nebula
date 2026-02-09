"use client";

type SegmentedOption = {
  value: string;
  label: string;
};

type SegmentedToggleProps = {
  label: string;
  value: string;
  options: SegmentedOption[];
  onChange: (nextValue: string) => void;
};

export default function SegmentedToggle({ label, value, options, onChange }: SegmentedToggleProps) {
  return (
    <div className="segmented-wrap">
      <span className="segmented-label">{label}</span>
      <div className="segmented" role="tablist" aria-label={label}>
        {options.map((option) => {
          const active = value === option.value;
          return (
            <button
              key={option.value}
              type="button"
              className={`segment ${active ? "active" : ""}`}
              role="tab"
              aria-selected={active}
              onClick={() => onChange(option.value)}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

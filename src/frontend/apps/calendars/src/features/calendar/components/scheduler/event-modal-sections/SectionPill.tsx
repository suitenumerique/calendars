import type { ReactNode } from "react";

interface SectionPillProps {
  icon: ReactNode;
  label: string;
  isActive: boolean;
  onClick: () => void;
}

export const SectionPill = ({ icon, label, isActive, onClick }: SectionPillProps) => {
  return (
    <button
      type="button"
      className={`section-pill ${isActive ? "section-pill--active" : ""}`}
      onClick={onClick}
      aria-pressed={isActive}
    >
      {icon}
      <span className="section-pill__label">{label}</span>
    </button>
  );
};

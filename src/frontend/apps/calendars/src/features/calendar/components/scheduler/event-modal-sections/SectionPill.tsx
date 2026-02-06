interface SectionPillProps {
  icon: string;
  label: string;
  isActive: boolean;
  onClick: () => void;
}

export const SectionPill = ({
  icon,
  label,
  isActive,
  onClick,
}: SectionPillProps) => {
  return (
    <button
      type="button"
      className={`section-pill ${isActive ? "section-pill--active" : ""}`}
      onClick={onClick}
      aria-pressed={isActive}
    >
      <span className="material-icons section-pill__icon">{icon}</span>
      <span className="section-pill__label">{label}</span>
    </button>
  );
};

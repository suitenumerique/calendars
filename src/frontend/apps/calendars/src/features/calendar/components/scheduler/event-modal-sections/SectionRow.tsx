import { type ReactNode } from "react";

interface SectionRowProps {
  icon: string;
  label: string;
  summary?: string;
  isEmpty?: boolean;
  isExpanded?: boolean;
  onToggle?: () => void;
  rightAction?: ReactNode;
  children?: ReactNode;
  alwaysOpen?: boolean;
  iconAlign?: "center" | "flex-start";
}

export const SectionRow = ({
  icon,
  label,
  summary,
  isEmpty = false,
  isExpanded = false,
  onToggle,
  rightAction,
  children,
  alwaysOpen = false,
  iconAlign = "center",
}: SectionRowProps) => {
  const iconAlignClass =
    iconAlign === "flex-start" ? "section-row--icon-start" : "";

  if (alwaysOpen) {
    return (
      <div className={`section-row section-row--always-open ${iconAlignClass}`}>
        <div className="section-row__icon">
          <span className="material-icons">{icon}</span>
        </div>
        <div className="section-row__body">{children}</div>
      </div>
    );
  }

  const isClickable = !!onToggle;

  return (
    <div
      className={`section-row ${isExpanded ? "section-row--expanded" : ""} ${
        isEmpty ? "section-row--empty" : ""
      } ${iconAlignClass}`}
    >
      <div
        className={`section-row__header ${
          isClickable ? "section-row__header--clickable" : ""
        }`}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (isClickable && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            onToggle?.();
          }
        }}
        role={isClickable ? "button" : undefined}
        tabIndex={isClickable ? 0 : undefined}
        aria-expanded={isClickable ? isExpanded : undefined}
      >
        <div className="section-row__icon">
          <span className="material-icons">{icon}</span>
        </div>
        <div className="section-row__label">
          {isEmpty ? label : summary || label}
        </div>
        {rightAction && (
          <div className="section-row__right-action">{rightAction}</div>
        )}
        {isClickable && (
          <div className="section-row__chevron">
            <span className="material-icons">
              {isExpanded ? "expand_less" : "expand_more"}
            </span>
          </div>
        )}
      </div>
      {isExpanded && children && (
        <div className="section-row__content">{children}</div>
      )}
    </div>
  );
};

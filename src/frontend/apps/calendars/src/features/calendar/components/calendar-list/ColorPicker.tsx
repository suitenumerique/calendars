/**
 * ColorPicker component.
 * Displays a palette of color buttons for calendar color selection.
 */

import { useTranslation } from "react-i18next";

import { DEFAULT_COLORS } from "./constants";

interface ColorPickerProps {
  value: string;
  onChange: (color: string) => void;
}

export const ColorPicker = ({ value, onChange }: ColorPickerProps) => {
  const { t } = useTranslation();

  return (
    <div className="calendar-modal__field">
      <label className="calendar-modal__label">
        {t("calendar.createCalendar.color")}
      </label>
      <div className="calendar-modal__colors">
        {DEFAULT_COLORS.map((c) => (
          <button
            key={c}
            type="button"
            className={`calendar-modal__color-btn ${
              value === c ? "calendar-modal__color-btn--selected" : ""
            }`}
            style={{ backgroundColor: c }}
            onClick={() => onChange(c)}
            aria-label={c}
          />
        ))}
      </div>
    </div>
  );
};

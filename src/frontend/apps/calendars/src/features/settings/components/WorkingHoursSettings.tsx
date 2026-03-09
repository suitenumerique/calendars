import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useRouter } from "next/router";

import {
  addToast,
  ToasterItem,
} from "@/features/ui/components/toaster/Toaster";

import { useWorkingHours } from "../api/useWorkingHours";
import {
  type AvailabilitySlot,
  type AvailabilitySlots,
  generateSlotId,
} from "../types";
import { AvailabilityRow } from "./AvailabilityRow";

interface AvailabilityFormProps {
  initialSlots: AvailabilitySlots;
  onSave: (slots: AvailabilitySlots) => Promise<void>;
  isSaving: boolean;
}

const AvailabilityForm = ({
  initialSlots,
  onSave,
  isSaving,
}: AvailabilityFormProps) => {
  const { t } = useTranslation();
  const router = useRouter();

  const [slots, setSlots] = useState<AvailabilitySlots>(initialSlots);

  const addSlot = useCallback(() => {
    setSlots((prev) => [
      ...prev,
      {
        id: generateSlotId(),
        when: { type: "recurring", day: "monday" },
        start: "09:00",
        end: "18:00",
      },
    ]);
  }, []);

  const removeSlot = useCallback((id: string) => {
    setSlots((prev) => prev.filter((s) => s.id !== id));
  }, []);

  const updateSlot = useCallback(
    (id: string, updates: Partial<AvailabilitySlot>) => {
      setSlots((prev) =>
        prev.map((s) => (s.id === id ? { ...s, ...updates } : s)),
      );
    },
    [],
  );

  const handleSave = async () => {
    try {
      await onSave(slots);
      addToast(
        <ToasterItem type="info">
          <span>{t("settings.workingHours.saved")}</span>
        </ToasterItem>,
      );
    } catch {
      addToast(
        <ToasterItem type="error">
          <span>{t("api.error.unexpected")}</span>
        </ToasterItem>,
      );
    }
  };

  return (
    <div className="working-hours">
      <div className="working-hours__header">
        <div className="working-hours__title-row">
          <Button
            color="neutral"
            size="small"
            icon={
              <span className="material-icons">arrow_back</span>
            }
            onClick={() => void router.push("/calendar")}
            aria-label={t("app_title")}
          />
          <h2>{t("settings.workingHours.title")}</h2>
        </div>
      </div>

      <p className="working-hours__description">
        {t("settings.workingHours.description")}
      </p>

      <div className="working-hours__grid">
        <div className="working-hours__grid-header">
          <span>{t("settings.workingHours.when")}</span>
          <span>{t("settings.workingHours.start")}</span>
          <span>{t("settings.workingHours.end")}</span>
          <span />
        </div>

        {slots.map((slot) => (
          <AvailabilityRow
            key={slot.id}
            slot={slot}
            onChange={updateSlot}
            onDelete={removeSlot}
          />
        ))}
      </div>

      <div className="working-hours__add-row">
        <Button
          color="neutral"
          size="small"
          icon={<span className="material-icons">add</span>}
          onClick={addSlot}
        >
          {t("settings.workingHours.addAvailability")}
        </Button>
      </div>

      <div className="working-hours__actions">
        <Button
          color="brand"
          onClick={() => void handleSave()}
          disabled={isSaving}
        >
          {t("settings.workingHours.save")}
        </Button>
      </div>
    </div>
  );
};

export const WorkingHoursSettings = () => {
  const { slots, isLoading, save, isSaving } = useWorkingHours();

  if (isLoading) {
    return (
      <div className="working-hours__loading">
        <span className="material-icons working-hours__spinner">
          hourglass_empty
        </span>
      </div>
    );
  }

  return (
    <AvailabilityForm
      key={JSON.stringify(slots)}
      initialSlots={slots}
      onSave={save}
      isSaving={isSaving}
    />
  );
};

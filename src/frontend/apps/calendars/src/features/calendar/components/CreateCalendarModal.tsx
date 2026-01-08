/**
 * Modal component for creating a new calendar.
 */

import { useState, useEffect } from "react";
import {
  Button,
  Input,
  Modal,
  ModalSize,
  useModal,
} from "@openfun/cunningham-react";
import { useTranslation } from "next-i18next";
import { useCreateCalendar } from "../hooks/useCalendars";
import { addToast, ToasterItem } from "@/features/ui/components/toaster/Toaster";
import { errorToString } from "@/features/api/APIError";

export const useCreateCalendarModal = () => {
  const { t } = useTranslation();
  const modal = useModal();
  const createCalendar = useCreateCalendar();
  const [name, setName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Reset form when modal opens
  useEffect(() => {
    if (modal.isOpen) {
      setName("");
      setIsSubmitting(false);
    }
  }, [modal.isOpen]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!name.trim()) {
      return;
    }

    setIsSubmitting(true);
    try {
      await createCalendar.mutateAsync({
        name: name.trim(),
      });
      addToast(
        <ToasterItem>
          <span>{t("calendar.created_success", { name: name.trim(), defaultValue: `Calendrier "${name.trim()}" créé avec succès` })}</span>
        </ToasterItem>
      );
      setName("");
      modal.close();
    } catch (error) {
      console.error("Failed to create calendar:", error);
      const errorMessage = errorToString(error);
      addToast(
        <ToasterItem type="error">
          <span>{errorMessage || t("calendar.created_error", { defaultValue: "Erreur lors de la création du calendrier" })}</span>
        </ToasterItem>
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    setName("");
    modal.close();
  };

  return {
    ...modal,
    Modal: (
      <Modal
        {...modal}
        title={t("calendar.create_modal.title", { defaultValue: "Créer un nouveau calendrier" })}
        size={ModalSize.SMALL}
        onClose={handleClose}
      >
        <form onSubmit={handleSubmit}>
          <Input
            label={t("calendar.create_modal.name_label", { defaultValue: "Nom du calendrier" })}
            value={name}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setName(e.target.value)}
            required
            disabled={isSubmitting}
            autoFocus
            placeholder={t("calendar.create_modal.name_placeholder", { defaultValue: "Mon calendrier" })}
          />
          <div style={{ display: "flex", gap: "1rem", justifyContent: "flex-end", marginTop: "1.5rem" }}>
            <Button
              type="button"
              color="secondary"
              onClick={handleClose}
              disabled={isSubmitting}
            >
              {t("common.cancel", { defaultValue: "Annuler" })}
            </Button>
            <Button
              type="submit"
              color="primary"
              disabled={!name.trim() || isSubmitting}
            >
              {isSubmitting
                ? t("common.creating", { defaultValue: "Création..." })
                : t("common.create", { defaultValue: "Créer" })}
            </Button>
          </div>
        </form>
      </Modal>
    ),
  };
};

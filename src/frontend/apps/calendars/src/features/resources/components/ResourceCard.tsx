import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";

import type { ResourceType } from "../types";

type ResourceCardProps = {
  name: string;
  id: string;
  resourceType: ResourceType;
  canAdmin: boolean;
  onDelete: (id: string) => void;
};

export const ResourceCard = ({
  name,
  id,
  resourceType,
  canAdmin,
  onDelete,
}: ResourceCardProps) => {
  const { t } = useTranslation();

  const icon = resourceType === "ROOM" ? "meeting_room" : "devices";

  return (
    <div className="resource-card">
      <div className="resource-card__icon">
        <span className="material-icons">{icon}</span>
      </div>
      <div className="resource-card__info">
        <div className="resource-card__name">{name}</div>
        <div className="resource-card__meta">
          <span className="resource-card__type">
            {t(`resources.types.${resourceType.toLowerCase()}`)}
          </span>
        </div>
      </div>
      {canAdmin && (
        <div className="resource-card__actions">
          <Button
            color="error"
            size="small"
            icon={
              <span className="material-icons">delete</span>
            }
            onClick={() => onDelete(id)}
            aria-label={t("resources.delete.button")}
          />
        </div>
      )}
    </div>
  );
};

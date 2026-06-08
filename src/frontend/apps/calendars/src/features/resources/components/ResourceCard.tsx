import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { Building, Computer, Trash } from "@gouvfr-lasuite/ui-kit/icons";

import type { ResourceType } from "../types";

type ResourceCardProps = {
  name: string;
  id: string;
  resourceType: ResourceType;
  canAdmin: boolean;
  onDelete: (id: string) => void;
};

export const ResourceCard = ({ name, id, resourceType, canAdmin, onDelete }: ResourceCardProps) => {
  const { t } = useTranslation();

  return (
    <div className="resource-card">
      <div className="resource-card__icon">
        {resourceType === "ROOM" ? <Building /> : <Computer />}
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
            icon={<Trash />}
            onClick={() => onDelete(id)}
            aria-label={t("resources.delete.button")}
          />
        </div>
      )}
    </div>
  );
};

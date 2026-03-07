import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input, useModal } from "@gouvfr-lasuite/cunningham-react";
import { useRouter } from "next/router";

import { useAuth } from "@/features/auth/Auth";
import { ResourceCard } from "./ResourceCard";
import { CreateResourceModal } from "./CreateResourceModal";
import { DeleteResourceModal } from "./DeleteResourceModal";
import type { ResourceType } from "../types";

type ResourcePrincipal = {
  id: string;
  name: string;
  resourceType: ResourceType;
};

type ResourceListProps = {
  resources: ResourcePrincipal[];
  isLoading: boolean;
  onRefresh: () => void;
};

export const ResourceList = ({
  resources,
  isLoading,
  onRefresh,
}: ResourceListProps) => {
  const { t } = useTranslation();
  const { user } = useAuth();
  const router = useRouter();
  const canAdmin = user?.can_admin ?? false;

  const createModal = useModal();
  const [deleteTarget, setDeleteTarget] = useState<{
    id: string;
    name: string;
  } | null>(null);

  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<ResourceType | "ALL">(
    "ALL",
  );

  const filtered = resources.filter((r) => {
    if (typeFilter !== "ALL" && r.resourceType !== typeFilter) return false;
    if (
      search &&
      !r.name.toLowerCase().includes(search.toLowerCase())
    ) {
      return false;
    }
    return true;
  });

  const handleDelete = useCallback((id: string) => {
    const resource = resources.find((r) => r.id === id);
    if (resource) {
      setDeleteTarget({ id, name: resource.name });
    }
  }, [resources]);

  return (
    <div className="resource-list">
      <div className="resource-list__header">
        <div className="resource-list__title-row">
          <Button
            color="neutral"
            size="small"
            icon={<span className="material-icons">arrow_back</span>}
            onClick={() => void router.push("/calendar")}
            aria-label={t("app_title")}
          />
          <h2>{t("resources.title")}</h2>
        </div>
        {canAdmin && (
          <Button
            color="brand"
            onClick={createModal.open}
            icon={<span className="material-icons">add</span>}
          >
            {t("resources.create.button")}
          </Button>
        )}
      </div>

      <div className="resource-list__filters">
        <Input
          label={t("resources.search")}
          value={search}
          onChange={(e) =>
            setSearch(
              (e.target as HTMLInputElement).value,
            )
          }
          fullWidth
        />
        <div className="resource-list__type-filters">
          <Button
            color={typeFilter === "ALL" ? "brand" : "neutral"}
            size="small"
            onClick={() => setTypeFilter("ALL")}
          >
            {t("resources.filters.all")}
          </Button>
          <Button
            color={typeFilter === "ROOM" ? "brand" : "neutral"}
            size="small"
            onClick={() => setTypeFilter("ROOM")}
          >
            {t("resources.types.room")}
          </Button>
          <Button
            color={typeFilter === "RESOURCE" ? "brand" : "neutral"}
            size="small"
            onClick={() => setTypeFilter("RESOURCE")}
          >
            {t("resources.types.resource")}
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="resource-list__loading">
          <span className="material-icons resource-list__spinner">
            hourglass_empty
          </span>
          <p>{t("resources.loading")}</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="resource-list__empty">
          <span className="material-icons">meeting_room</span>
          <p>
            {search || typeFilter !== "ALL"
              ? t("resources.noResults")
              : t("resources.empty")}
          </p>
        </div>
      ) : (
        <div className="resource-list__grid">
          {filtered.map((resource) => (
            <ResourceCard
              key={resource.id}
              name={resource.name}
              id={resource.id}
              resourceType={resource.resourceType}
              canAdmin={canAdmin}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      {createModal.isOpen && (
        <CreateResourceModal
          isOpen={createModal.isOpen}
          onClose={createModal.close}
          onSuccess={onRefresh}
        />
      )}

      {deleteTarget && (
        <DeleteResourceModal
          isOpen={!!deleteTarget}
          id={deleteTarget.id}
          name={deleteTarget.name}
          onClose={() => setDeleteTarget(null)}
          onSuccess={onRefresh}
        />
      )}
    </div>
  );
};

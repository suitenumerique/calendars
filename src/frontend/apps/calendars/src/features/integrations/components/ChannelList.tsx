import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, useModal } from "@gouvfr-lasuite/cunningham-react";
import { useRouter } from "next/router";

import type { Channel } from "../types";
import { useChannels } from "../api/useChannels";
import { ChannelCard } from "./ChannelCard";
import { ChannelModal } from "./ChannelModal";
import { DeleteChannelModal } from "./DeleteChannelModal";

export const ChannelList = () => {
  const { t } = useTranslation();
  const router = useRouter();
  const { data: channels, isLoading } = useChannels();
  const createModal = useModal();

  const [editTarget, setEditTarget] =
    useState<Channel | null>(null);
  const [deleteTarget, setDeleteTarget] =
    useState<Channel | null>(null);

  return (
    <div className="channel-list">
      <div className="channel-list__header">
        <div className="channel-list__title-row">
          <Button
            color="neutral"
            size="small"
            icon={
              <span className="material-icons">
                arrow_back
              </span>
            }
            onClick={() => void router.push("/")}
            aria-label={t("app_title")}
          />
          <h2>{t("integrations.title")}</h2>
        </div>
        <Button
          color="brand"
          onClick={createModal.open}
          icon={
            <span className="material-icons">add</span>
          }
        >
          {t("integrations.create.button")}
        </Button>
      </div>

      <p className="channel-list__description">
        {t("integrations.description")}
      </p>

      {isLoading ? (
        <div className="channel-list__loading">
          <span className="material-icons channel-list__spinner">
            hourglass_empty
          </span>
          <p>{t("integrations.loading")}</p>
        </div>
      ) : !channels || channels.length === 0 ? (
        <div className="channel-list__empty">
          <span className="material-icons">
            integration_instructions
          </span>
          <p>{t("integrations.empty")}</p>
        </div>
      ) : (
        <div className="channel-list__grid">
          {channels.map((channel) => (
            <ChannelCard
              key={channel.id}
              channel={channel}
              onEdit={setEditTarget}
              onDelete={setDeleteTarget}
            />
          ))}
        </div>
      )}

      {createModal.isOpen && (
        <ChannelModal
          isOpen={createModal.isOpen}
          onClose={createModal.close}
        />
      )}

      {editTarget && (
        <ChannelModal
          isOpen={!!editTarget}
          channel={editTarget}
          onClose={() => setEditTarget(null)}
        />
      )}

      {deleteTarget && (
        <DeleteChannelModal
          isOpen={!!deleteTarget}
          id={deleteTarget.id}
          name={deleteTarget.name}
          onClose={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
};

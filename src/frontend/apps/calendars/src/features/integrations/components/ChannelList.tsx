import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, useModal } from "@gouvfr-lasuite/cunningham-react";
import { useRouter } from "next/router";

import {
  addToast,
  ToasterItem,
} from "@/features/ui/components/toaster/Toaster";
import { useChannels, useRegenerateToken } from "../api/useChannels";
import { ChannelCard } from "./ChannelCard";
import { CreateChannelModal } from "./CreateChannelModal";
import { DeleteChannelModal } from "./DeleteChannelModal";
import { TokenRevealBox } from "./TokenRevealBox";

export const ChannelList = () => {
  const { t } = useTranslation();
  const router = useRouter();
  const { data: channels, isLoading } = useChannels();
  const regenerateToken = useRegenerateToken();
  const createModal = useModal();

  const [deleteTarget, setDeleteTarget] = useState<{
    id: string;
    name: string;
  } | null>(null);

  const [regeneratedToken, setRegeneratedToken] = useState<
    string | null
  >(null);

  const handleRegenerate = async (id: string) => {
    try {
      const result = await regenerateToken.mutateAsync(id);
      setRegeneratedToken(result.token);
      addToast(
        <ToasterItem type="info">
          <span>
            {t("integrations.regenerate.success")}
          </span>
        </ToasterItem>,
      );
    } catch {
      addToast(
        <ToasterItem type="error">
          <span>
            {t("integrations.regenerate.error")}
          </span>
        </ToasterItem>,
      );
    }
  };

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
            onClick={() => void router.push("/calendar")}
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

      {regeneratedToken && (
        <div className="channel-list__token-banner">
          <p>{t("integrations.regenerate.tokenWarning")}</p>
          <TokenRevealBox token={regeneratedToken} />
          <Button
            color="neutral"
            size="small"
            onClick={() => setRegeneratedToken(null)}
          >
            {t("common.close")}
          </Button>
        </div>
      )}

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
              onDelete={(id) => {
                const ch = channels.find(
                  (c) => c.id === id,
                );
                if (ch) {
                  setDeleteTarget({
                    id,
                    name: ch.name,
                  });
                }
              }}
              onRegenerate={(id) =>
                void handleRegenerate(id)
              }
            />
          ))}
        </div>
      )}

      {createModal.isOpen && (
        <CreateChannelModal
          isOpen={createModal.isOpen}
          onClose={createModal.close}
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

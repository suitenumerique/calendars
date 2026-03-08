import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";

import type { Channel } from "../types";

type ChannelCardProps = {
  channel: Channel;
  onDelete: (id: string) => void;
  onRegenerate: (id: string) => void;
};

export const ChannelCard = ({
  channel,
  onDelete,
  onRegenerate,
}: ChannelCardProps) => {
  const { t } = useTranslation();

  return (
    <div className="channel-card">
      <div className="channel-card__icon">
        <span className="material-icons">key</span>
      </div>
      <div className="channel-card__info">
        <div className="channel-card__name">{channel.name}</div>
        <div className="channel-card__meta">
          <span className="channel-card__role">
            {t(`integrations.roles.${channel.role}`)}
          </span>
          {channel.caldav_path && (
            <span className="channel-card__scope">
              {channel.caldav_path}
            </span>
          )}
          {channel.last_used_at && (
            <span className="channel-card__last-used">
              {t("integrations.lastUsed", {
                date: new Date(
                  channel.last_used_at,
                ).toLocaleDateString(),
              })}
            </span>
          )}
        </div>
      </div>
      <div className="channel-card__actions">
        <Button
          color="neutral"
          size="small"
          icon={
            <span className="material-icons">refresh</span>
          }
          onClick={() => onRegenerate(channel.id)}
          aria-label={t("integrations.regenerate.button")}
        />
        <Button
          color="error"
          size="small"
          icon={
            <span className="material-icons">delete</span>
          }
          onClick={() => onDelete(channel.id)}
          aria-label={t("integrations.delete.button")}
        />
      </div>
    </div>
  );
};

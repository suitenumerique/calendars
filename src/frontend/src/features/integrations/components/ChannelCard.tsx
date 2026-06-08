import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { Edit, Globe, Key, PlugOn, Puzzle, Trash } from "@gouvfr-lasuite/ui-kit/icons";

import type { Channel } from "../types";

type ChannelCardProps = {
  channel: Channel;
  onEdit: (channel: Channel) => void;
  onDelete: (channel: Channel) => void;
};

const TYPE_ICONS: Record<string, ReactNode> = {
  caldav: <Key />,
  "ical-feed": <Globe />,
  webhook: <PlugOn />,
};

export const ChannelCard = ({ channel, onEdit, onDelete }: ChannelCardProps) => {
  const { t } = useTranslation();

  const typeLabel = t(`integrations.types.${channel.type}.title`, channel.type);

  return (
    <div className={`channel-card${channel.is_active ? "" : " channel-card--inactive"}`}>
      <div className="channel-card__icon">{TYPE_ICONS[channel.type] ?? <Puzzle />}</div>
      <div className="channel-card__info">
        <div className="channel-card__name">
          {channel.name}
          {!channel.is_active && (
            <span className="channel-card__badge">{t("integrations.edit.inactiveBadge")}</span>
          )}
        </div>
        <div className="channel-card__meta">
          <span className="channel-card__type">{typeLabel}</span>
          {channel.last_used_at && (
            <span className="channel-card__last-used">
              {t("integrations.lastUsed", {
                date: new Date(channel.last_used_at).toLocaleDateString(),
              })}
            </span>
          )}
        </div>
      </div>
      <div className="channel-card__actions">
        <Button
          color="neutral"
          size="small"
          icon={<Edit />}
          onClick={() => onEdit(channel)}
          aria-label={t("integrations.edit.button")}
        />
        <Button
          color="error"
          size="small"
          icon={<Trash />}
          onClick={() => onDelete(channel)}
          aria-label={t("integrations.delete.button")}
        />
      </div>
    </div>
  );
};

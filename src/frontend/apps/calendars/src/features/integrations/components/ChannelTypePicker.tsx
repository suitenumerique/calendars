import { useTranslation } from "react-i18next";

export type ChannelPickerType = "caldav" | "webhook";

type ChannelTypeMetadata = {
  type: ChannelPickerType;
  titleKey: string;
  descriptionKey: string;
  icon: string;
  disabled?: boolean;
};

const CHANNEL_TYPE_METADATA: Record<
  ChannelPickerType,
  ChannelTypeMetadata
> = {
  caldav: {
    type: "caldav",
    titleKey: "integrations.types.caldav.title",
    descriptionKey: "integrations.types.caldav.description",
    icon: "key",
  },
  webhook: {
    type: "webhook",
    titleKey: "integrations.types.webhook.title",
    descriptionKey: "integrations.types.webhook.description",
    icon: "webhook",
    disabled: true,
  },
};

type ChannelTypeCardProps = {
  title: string;
  description: string;
  icon: string;
  disabled?: boolean;
  comingSoonLabel: string;
  onClick: () => void;
};

const ChannelTypeCard = ({
  title,
  description,
  icon,
  disabled,
  comingSoonLabel,
  onClick,
}: ChannelTypeCardProps) => (
  <button
    type="button"
    className={`channel-type-card${
      disabled ? " channel-type-card--disabled" : ""
    }`}
    onClick={onClick}
    disabled={disabled}
  >
    {disabled && (
      <span className="channel-type-card__badge">
        {comingSoonLabel}
      </span>
    )}
    <div className="channel-type-card__icon">
      <span className="material-icons">{icon}</span>
    </div>
    <div className="channel-type-card__content">
      <h3 className="channel-type-card__title">{title}</h3>
      <p className="channel-type-card__description">
        {description}
      </p>
    </div>
  </button>
);

type ChannelTypePickerProps = {
  onSelect: (type: ChannelPickerType) => void;
};

export const ChannelTypePicker = ({
  onSelect,
}: ChannelTypePickerProps) => {
  const { t } = useTranslation();

  return (
    <div className="channel-type-selector">
      <p className="channel-type-selector__subtitle">
        {t("integrations.create.chooseType")}
      </p>
      <div className="channel-type-selector__cards">
        {Object.values(CHANNEL_TYPE_METADATA).map(
          (metadata) => (
            <ChannelTypeCard
              key={metadata.type}
              title={t(metadata.titleKey)}
              description={t(metadata.descriptionKey)}
              icon={metadata.icon}
              disabled={metadata.disabled}
              comingSoonLabel={t("common.comingSoon")}
              onClick={() => onSelect(metadata.type)}
            />
          ),
        )}
      </div>
    </div>
  );
};

export const getChannelTypeTitleKey = (type: ChannelPickerType) =>
  CHANNEL_TYPE_METADATA[type].titleKey;

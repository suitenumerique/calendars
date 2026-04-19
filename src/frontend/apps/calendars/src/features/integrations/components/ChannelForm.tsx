import { useTranslation } from "react-i18next";
import {
  Button,
  Input,
  Switch,
} from "@gouvfr-lasuite/cunningham-react";

import type { ChannelScopeValue } from "../types";
import { ScopeEditor } from "./ScopeEditor";

type ChannelFormProps = {
  name: string;
  onNameChange: (name: string) => void;
  scopes: ChannelScopeValue[];
  onScopesChange: (scopes: ChannelScopeValue[]) => void;
  /** Show the active toggle. Omit on create. */
  isActive?: boolean;
  onIsActiveChange?: (value: boolean) => void;
  /** Show the regenerate-token row. Omit on create. */
  onRegenerate?: () => void;
  /** Show the scope editor. Default true. Hidden for channel types
   *  whose scopes are not user-configurable (e.g. ical-feed). */
  showScopes?: boolean;
  disabled?: boolean;
};

export const ChannelForm = ({
  name,
  onNameChange,
  scopes,
  onScopesChange,
  isActive,
  onIsActiveChange,
  onRegenerate,
  showScopes = true,
  disabled = false,
}: ChannelFormProps) => {
  const { t } = useTranslation();
  const showActive =
    isActive !== undefined && onIsActiveChange !== undefined;

  return (
    <div className="channel-edit-modal">
      <Input
        label={t("integrations.create.nameLabel")}
        value={name}
        onChange={(e) =>
          onNameChange((e.target as HTMLInputElement).value)
        }
        fullWidth
        disabled={disabled}
      />
      {showActive && (
        <Switch
          label={t("integrations.edit.activeLabel")}
          checked={isActive}
          onChange={(e) =>
            onIsActiveChange(
              (e.target as HTMLInputElement).checked,
            )
          }
          disabled={disabled}
        />
      )}
      {showScopes && (
        <ScopeEditor
          scopes={scopes}
          onChange={onScopesChange}
          disabled={disabled}
        />
      )}
      {onRegenerate && (
        <div className="channel-edit-modal__regenerate">
          <div>
            <div className="channel-edit-modal__regenerate-title">
              {t("integrations.regenerate.title")}
            </div>
            <p className="channel-edit-modal__regenerate-description">
              {t("integrations.regenerate.description")}
            </p>
          </div>
          <Button
            color="neutral"
            size="small"
            onClick={onRegenerate}
            disabled={disabled}
            icon={
              <span className="material-icons">refresh</span>
            }
          >
            {t("integrations.regenerate.button")}
          </Button>
        </div>
      )}
    </div>
  );
};

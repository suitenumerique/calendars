import { useTranslation } from "react-i18next";
import { Checkbox } from "@gouvfr-lasuite/cunningham-react";
import { CHANNEL_SCOPES, type ChannelScopeValue } from "../types";

type ScopeEditorProps = {
  scopes: ChannelScopeValue[];
  onChange: (scopes: ChannelScopeValue[]) => void;
  disabled?: boolean;
};

export const ScopeEditor = ({ scopes, onChange, disabled = false }: ScopeEditorProps) => {
  const { t } = useTranslation();

  const toggle = (scope: ChannelScopeValue) => {
    if (scopes.includes(scope)) {
      onChange(scopes.filter((s) => s !== scope));
    } else {
      onChange([...scopes, scope]);
    }
  };

  return (
    <div className="scope-editor">
      {CHANNEL_SCOPES.map((scope) => (
        <Checkbox
          key={scope}
          label={t(`integrations.scopes.${scope.replace(":", "_")}`)}
          checked={scopes.includes(scope)}
          onChange={() => toggle(scope)}
          disabled={disabled}
        />
      ))}
    </div>
  );
};

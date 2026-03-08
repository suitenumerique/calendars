import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";

import {
  addToast,
  ToasterItem,
} from "@/features/ui/components/toaster/Toaster";

type TokenRevealBoxProps = {
  token: string;
};

export const TokenRevealBox = ({
  token,
}: TokenRevealBoxProps) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(token);
    setCopied(true);
    addToast(
      <ToasterItem type="info">
        <span>{t("integrations.token.copied")}</span>
      </ToasterItem>,
    );
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="token-reveal-box">
      <code className="token-reveal-box__token">
        {token}
      </code>
      <Button
        color="brand"
        size="small"
        icon={
          <span className="material-icons">
            {copied ? "check" : "content_copy"}
          </span>
        }
        onClick={() => void handleCopy()}
        aria-label={t("integrations.token.copy")}
      />
    </div>
  );
};

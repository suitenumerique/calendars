import { useTranslation } from "react-i18next";
import { Button, Modal, ModalSize } from "@gouvfr-lasuite/cunningham-react";
import { TokenRevealBox } from "./TokenRevealBox";

type TokenRevealModalProps = {
  isOpen: boolean;
  title: string;
  warning: string;
  token: string;
  /**
   * When provided, render a CalDAV credential bundle (URL + username +
   * password) instead of a bare token. The token is the password value;
   * url and username are shown alongside it with copy buttons so users
   * have everything they need to configure a client.
   */
  caldavUrl?: string;
  caldavUsername?: string;
  onClose: () => void;
};

export const TokenRevealModal = ({
  isOpen,
  title,
  warning,
  token,
  caldavUrl,
  caldavUsername,
  onClose,
}: TokenRevealModalProps) => {
  const { t } = useTranslation();
  // Drive the CalDAV credential block off the URL alone: the server URL
  // is the load-bearing piece a user needs, so don't hide it just because
  // the username (the signed-in email) hasn't resolved yet. The username
  // field is rendered conditionally below.
  const hasCaldavUrl = Boolean(caldavUrl);
  const hasCaldavUsername = Boolean(caldavUsername);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size={ModalSize.MEDIUM}
      title={title}
      actions={
        <Button color="brand" onClick={onClose}>
          {t("common.close")}
        </Button>
      }
    >
      <div className="channel-edit-modal">
        <p>{warning}</p>
        {hasCaldavUrl && (
          <>
            <label className="token-reveal-box__label">{t("integrations.caldav.serverUrl")}</label>
            <TokenRevealBox token={caldavUrl!} />
            {hasCaldavUsername && (
              <>
                <label className="token-reveal-box__label">
                  {t("integrations.caldav.username")}
                </label>
                <TokenRevealBox token={caldavUsername!} />
              </>
            )}
            <label className="token-reveal-box__label">{t("integrations.caldav.password")}</label>
          </>
        )}
        <TokenRevealBox token={token} />
      </div>
    </Modal>
  );
};

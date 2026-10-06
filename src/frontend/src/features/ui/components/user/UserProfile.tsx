import { UserMenu } from "@gouvfr-lasuite/ui-components";
import { useAuth, logout } from "@/features/auth/Auth";
import { useConfig } from "@/features/config/ConfigProvider";
import { LanguagePickerUserMenu } from "@/features/layouts/components/header/Header";
import { LoginButton } from "@/features/auth/components/LoginButton";

export const UserProfile = () => {
  const { user } = useAuth();
  const { config } = useConfig();

  return (
    <>
      {user ? (
        <UserMenu
          user={user}
          logout={logout}
          termOfServiceUrl={config?.FRONTEND_TERMS_OF_SERVICE_URL ?? undefined}
          actions={<LanguagePickerUserMenu />}
        />
      ) : (
        <LoginButton />
      )}
    </>
  );
};

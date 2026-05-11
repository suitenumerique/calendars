import React, {
  PropsWithChildren,
  useCallback,
  useEffect,
  useState,
} from "react";

import { fetchAPI } from "@/features/api/fetchApi";
import { User } from "@/features/auth/types";
import { baseApiUrl } from "../api/utils";
import { APIError } from "../api/APIError";
import { SpinnerPage } from "@/features/ui/components/spinner/SpinnerPage";

export const logout = () => {
  window.location.replace(new URL("logout/", baseApiUrl()).href);
};

export const login = (returnTo?: string) => {
  const url = new URL("authenticate/", baseApiUrl());
  if (returnTo) {
    url.searchParams.set("returnTo", returnTo);
  }
  window.location.replace(url.href);
};

interface AuthContextInterface {
  user?: User | null;
  init?: () => Promise<User | null>;
  refreshUser?: () => Promise<void>;
}

export const AuthContext = React.createContext<AuthContextInterface>({});

export const useAuth = () => React.useContext(AuthContext);

export const Auth = ({
  children,
  redirect,
}: PropsWithChildren & { redirect?: boolean }) => {
  const [user, setUser] = useState<User | null>();

  const init = useCallback(async () => {
    try {
      // skipAuthRedirect: this boot probe runs on public pages too, where a
      // 401 is the expected anonymous case — we don't want fetchAPI's
      // default redirect there. The explicit branches below pick the right
      // behavior based on `redirect`.
      const response = await fetchAPI(`users/me/`, { skipAuthRedirect: true });
      const data = (await response.json()) as User;
      setUser(data);
      return data;
    } catch (error) {
      if (redirect && error instanceof APIError && error.code === 401) {
        login(typeof window !== "undefined" ? window.location.href : undefined);
      } else {
        setUser(null);
      }
      return null;
    }
  }, [redirect]);

  const refreshUser = async () => {
    void init();
  };

  const shouldRedirectNoAccess = redirect && user?.can_access === false;

  useEffect(() => {
    void init();
  }, [init]);

  useEffect(() => {
    if (shouldRedirectNoAccess) {
      window.location.href = "/no-access";
    }
  }, [shouldRedirectNoAccess]);

  if (user === undefined || shouldRedirectNoAccess) {
    return <SpinnerPage />;
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        init,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

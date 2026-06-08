import { Auth } from "@/features/auth/Auth";

/**
 * This layout is used for the global contexts (auth, etc).
 * By default, unauthenticated users are redirected to the login flow.
 * Pass noRedirect on public pages (homepage, error pages) to skip this.
 */
export const GlobalLayout = ({
  children,
  noRedirect,
}: {
  children: React.ReactNode;
  noRedirect?: boolean;
}) => {
  return <Auth redirect={!noRedirect}>{children}</Auth>;
};

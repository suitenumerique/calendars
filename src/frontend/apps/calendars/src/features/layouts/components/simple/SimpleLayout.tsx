import { MainLayout } from "@gouvfr-lasuite/ui-kit";
import { GlobalLayout } from "../global/GlobalLayout";
import { HeaderRight } from "../header/Header";
import { Toaster } from "@/features/ui/components/toaster/Toaster";
import { LeftPanelMobile } from "@/features/layouts/components/left-panel/LeftPanelMobile";
import { useLeftPanel } from "../../contexts/LeftPanelContext";

export const getSimpleLayout = (page: React.ReactElement) => {
  return <SimpleLayout>{page}</SimpleLayout>;
};

/**
 * This layout is used for the simple pages.
 * It is used to display the header and provide
 * Auth context to the children.
 */
export const SimpleLayout = ({ children }: { children: React.ReactNode }) => {
  const { isLeftPanelOpen, setIsLeftPanelOpen } = useLeftPanel();
  return (
    <div>
      <GlobalLayout noRedirect>
        <MainLayout
          enableResize
          hideLeftPanelOnDesktop={true}
          isLeftPanelOpen={isLeftPanelOpen}
          setIsLeftPanelOpen={setIsLeftPanelOpen}
          leftPanelContent={<LeftPanelMobile />}
          rightHeaderContent={<HeaderRight />}
        >
          {children}
          <Toaster />
        </MainLayout>
      </GlobalLayout>
    </div>
  );
};

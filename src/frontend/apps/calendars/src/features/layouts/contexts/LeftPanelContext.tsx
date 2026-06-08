import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

interface LeftPanelContextType {
  isLeftPanelOpen: boolean;
  setIsLeftPanelOpen: (open: boolean) => void;
}

const LeftPanelContext = createContext<LeftPanelContextType | undefined>(undefined);

export const useLeftPanel = () => {
  const context = useContext(LeftPanelContext);
  if (!context) {
    throw new Error("useLeftPanel must be used within a LeftPanelProvider");
  }
  return context;
};

interface LeftPanelProviderProps {
  children: ReactNode;
}

export const LeftPanelProvider = ({ children }: LeftPanelProviderProps) => {
  const [isLeftPanelOpen, setIsLeftPanelOpen] = useState(false);

  const value = useMemo(
    () => ({ isLeftPanelOpen, setIsLeftPanelOpen }),
    [isLeftPanelOpen, setIsLeftPanelOpen],
  );

  return <LeftPanelContext.Provider value={value}>{children}</LeftPanelContext.Provider>;
};

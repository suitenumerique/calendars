import { createContext, useContext, useState, type PropsWithChildren } from "react";

export interface AppContextType {
  theme: string;
  setTheme: (theme: string) => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export const useAppContext = () => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error("useAppContext must be used within an AppContextProvider");
  }
  return context;
};

export const AppContextProvider = ({ children }: PropsWithChildren) => {
  const [theme, setTheme] = useState<string>("default");
  return <AppContext.Provider value={{ theme, setTheme }}>{children}</AppContext.Provider>;
};

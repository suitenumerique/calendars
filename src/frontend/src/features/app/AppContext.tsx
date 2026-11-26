import { createContext, useContext, useState, type PropsWithChildren } from "react";
import {
  loadColorScheme,
  saveColorScheme,
  type ColorScheme,
} from "@/features/ui/theme/colorScheme";

export interface AppContextType {
  theme: string;
  setTheme: (theme: string) => void;
  colorScheme: ColorScheme;
  setColorScheme: (colorScheme: ColorScheme) => void;
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
  const [colorScheme, setColorSchemeState] = useState<ColorScheme>(loadColorScheme);

  const setColorScheme = (scheme: ColorScheme) => {
    saveColorScheme(scheme);
    setColorSchemeState(scheme);
  };

  return (
    <AppContext.Provider value={{ theme, setTheme, colorScheme, setColorScheme }}>
      {children}
    </AppContext.Provider>
  );
};

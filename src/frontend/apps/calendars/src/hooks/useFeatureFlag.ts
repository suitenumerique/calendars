import { useConfig } from "@/features/config/ConfigProvider";

export enum FeatureFlag {
  ADMIN_CHANNELS = "ADMIN_CHANNELS",
  ADMIN_AVAILABILITIES = "ADMIN_AVAILABILITIES",
  ADMIN_RESOURCES = "ADMIN_RESOURCES",
}

export const useFeatureFlag = (flag: FeatureFlag): boolean => {
  const { config } = useConfig();

  switch (flag) {
    case FeatureFlag.ADMIN_CHANNELS:
      return config?.FEATURE_ADMIN_CHANNELS ?? true;
    case FeatureFlag.ADMIN_AVAILABILITIES:
      return config?.FEATURE_ADMIN_AVAILABILITIES ?? true;
    case FeatureFlag.ADMIN_RESOURCES:
      return config?.FEATURE_ADMIN_RESOURCES ?? true;
    default:
      return false;
  }
};

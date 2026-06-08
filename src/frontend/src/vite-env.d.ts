/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly NEXT_PUBLIC_API_ORIGIN?: string;
  readonly NEXT_PUBLIC_DEFAULT_LANGUAGE?: string;
  readonly NEXT_PUBLIC_FORCED_DEFAULT_LANGUAGE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

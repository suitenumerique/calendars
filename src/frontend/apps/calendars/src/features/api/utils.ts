export const getOrigin = () => {
  return (
    process.env.NEXT_PUBLIC_API_ORIGIN ||
    (typeof window !== "undefined" ? window.location.origin : "")
  );
};
export const baseApiUrl = (apiVersion: string = "1.0") => {
  const origin = getOrigin();
  return `${origin}/api/v${apiVersion}/`;
};

export const isJson = (str: string) => {
  try {
    JSON.parse(str);
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
  } catch (e) {
    return false;
  }
  return true;
};

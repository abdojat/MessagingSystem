export function isChannelListQueryKey(queryKey: readonly unknown[]): boolean {
  const params = queryKey[1];
  return (
    queryKey.length === 2 &&
    queryKey[0] === "/channels" &&
    typeof params === "object" &&
    params !== null &&
    "scope" in params
  );
}

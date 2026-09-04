export type RawSearchParams = Record<string, string | string[] | undefined>;

export function firstParam(params: RawSearchParams, key: string): string | undefined {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}

import { readFile } from "node:fs/promises";
import { dirname, isAbsolute, resolve } from "node:path";

/** Effective configuration for the local OSS runtime. */
export interface LocalRuntimeConfig {
  /** Interface to bind. Loopback is the secure default. */
  readonly host: string;
  /** HTTP port. Use `0` only for tests or embedded usage. */
  readonly port: number;
  /** Absolute path of the append-only local event store. */
  readonly dataFile: string;
  /** Explicit acknowledgement required before binding outside loopback. */
  readonly allowUnsafeNetwork: boolean;
  /** Configuration file loaded, when one exists. */
  readonly configFile?: string;
}

interface ConfigDocument {
  readonly server?: {
    readonly host?: unknown;
    readonly port?: unknown;
    readonly dataFile?: unknown;
    readonly allowUnsafeNetwork?: unknown;
  };
}

/** Options used to load local runtime configuration. */
export interface LoadConfigOptions {
  readonly cwd?: string;
  readonly env?: Readonly<Record<string, string | undefined>>;
}

/**
 * Loads configuration with deterministic precedence: environment, JSON file,
 * then secure defaults. Relative data paths are resolved beside the config
 * file so behavior does not change with the launch directory.
 */
export async function loadRuntimeConfig(
  options: LoadConfigOptions = {},
): Promise<LocalRuntimeConfig> {
  const cwd = resolve(options.cwd ?? process.cwd());
  const env = options.env ?? process.env;
  const requestedConfig = env.CAUSENTRA_CONFIG;
  const configFile = resolve(cwd, requestedConfig ?? "causentra.config.json");
  const document = await readConfigDocument(configFile, requestedConfig !== undefined);
  const server = document?.server;

  const fileHost = optionalString(server?.host, "server.host");
  const filePort = optionalPort(server?.port, "server.port");
  const fileData = optionalString(server?.dataFile, "server.dataFile");
  const fileUnsafe = optionalBoolean(
    server?.allowUnsafeNetwork,
    "server.allowUnsafeNetwork",
  );
  const host = env.CAUSENTRA_HOST ?? fileHost ?? "127.0.0.1";
  const port = parsePort(env.CAUSENTRA_PORT, filePort ?? 4318);
  const dataValue = env.CAUSENTRA_DATA_FILE ?? fileData ?? ".causentra/events.ndjson";
  const dataBase = env.CAUSENTRA_DATA_FILE !== undefined ? cwd : dirname(configFile);
  const dataFile = isAbsolute(dataValue) ? dataValue : resolve(dataBase, dataValue);
  const allowUnsafeNetwork = parseBoolean(
    env.CAUSENTRA_ALLOW_UNSAFE_NETWORK,
    fileUnsafe ?? false,
    "CAUSENTRA_ALLOW_UNSAFE_NETWORK",
  );

  return {
    host,
    port,
    dataFile,
    allowUnsafeNetwork,
    ...(document === undefined ? {} : { configFile }),
  };
}

async function readConfigDocument(
  file: string,
  required: boolean,
): Promise<ConfigDocument | undefined> {
  let contents: string;
  try {
    contents = await readFile(file, "utf8");
  } catch (error) {
    if (!required && isMissingFile(error)) return undefined;
    if (required && isMissingFile(error)) {
      throw new Error(`Configuration file was not found: ${file}`);
    }
    throw error;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(contents);
  } catch (error) {
    throw new Error(`Configuration file is not valid JSON: ${file}`, { cause: error });
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new TypeError("Configuration root must be a JSON object");
  }
  const server = (parsed as { server?: unknown }).server;
  if (server !== undefined && (typeof server !== "object" || server === null || Array.isArray(server))) {
    throw new TypeError("server configuration must be a JSON object");
  }
  return parsed as ConfigDocument;
}

function optionalString(value: unknown, field: string): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new TypeError(`${field} must be a non-empty string`);
  }
  return value;
}

function optionalPort(value: unknown, field: string): number | undefined {
  if (value === undefined) return undefined;
  if (!Number.isSafeInteger(value) || (value as number) < 0 || (value as number) > 65_535) {
    throw new RangeError(`${field} must be an integer from 0 to 65535`);
  }
  return value as number;
}

function optionalBoolean(value: unknown, field: string): boolean | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "boolean") throw new TypeError(`${field} must be a boolean`);
  return value;
}

function parseBoolean(
  value: string | undefined,
  fallback: boolean,
  field: string,
): boolean {
  if (value === undefined) return fallback;
  if (value === "true") return true;
  if (value === "false") return false;
  throw new TypeError(`${field} must be true or false`);
}

function parsePort(value: string | undefined, fallback: number): number {
  if (value === undefined) return fallback;
  if (!/^\d{1,5}$/u.test(value)) {
    throw new RangeError("CAUSENTRA_PORT must be an integer from 0 to 65535");
  }
  return optionalPort(Number(value), "CAUSENTRA_PORT") ?? fallback;
}

function isMissingFile(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "ENOENT"
  );
}

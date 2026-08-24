import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { Ajv2020, type AnySchema } from "ajv/dist/2020.js";

const schemaPath = fileURLToPath(new URL("../../schema/signature-v1.schema.json", import.meta.url));
const validDirectory = fileURLToPath(
  new URL("../../fixtures/signature/v1/valid/", import.meta.url),
);
const invalidDirectory = fileURLToPath(
  new URL("../../fixtures/signature/v1/invalid/", import.meta.url),
);

test("detached signature schema accepts valid profiles and rejects contract violations", async () => {
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  const schema = JSON.parse(await readFile(schemaPath, "utf8")) as AnySchema;
  const validate = ajv.compile(schema);

  for (const filename of await jsonFiles(validDirectory)) {
    const envelope: unknown = JSON.parse(await readFile(`${validDirectory}/${filename}`, "utf8"));
    assert.equal(validate(envelope), true, `${filename}: ${ajv.errorsText(validate.errors)}`);
  }
  for (const filename of await jsonFiles(invalidDirectory)) {
    const envelope: unknown = JSON.parse(await readFile(`${invalidDirectory}/${filename}`, "utf8"));
    assert.equal(validate(envelope), false, `${filename} should fail signature schema`);
  }
});

async function jsonFiles(directory: string): Promise<string[]> {
  return (await readdir(directory)).filter((file) => file.endsWith(".json")).sort();
}

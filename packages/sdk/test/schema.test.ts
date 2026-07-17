import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { Ajv2020, type AnySchema } from "ajv/dist/2020.js";
import { EventValidationError, validateEvent } from "../src/index.js";

const schemaPath = fileURLToPath(
  new URL("../../schema/runtime-event-v1.schema.json", import.meta.url),
);
const validDirectory = fileURLToPath(new URL("../../fixtures/v1/valid/", import.meta.url));
const invalidDirectory = fileURLToPath(new URL("../../fixtures/v1/invalid/", import.meta.url));

test("JSON Schema and runtime validator agree on compatibility fixtures", async () => {
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  ajv.addFormat("date-time", {
    type: "string",
    validate: (value: string) => !Number.isNaN(Date.parse(value)),
  });
  const schema = JSON.parse(await readFile(schemaPath, "utf8")) as AnySchema;
  const validateSchema = ajv.compile(schema);

  for (const filename of await jsonFiles(validDirectory)) {
    const event: unknown = JSON.parse(await readFile(`${validDirectory}/${filename}`, "utf8"));
    assert.equal(validateSchema(event), true, `${filename}: ${ajv.errorsText(validateSchema.errors)}`);
    assert.doesNotThrow(() => validateEvent(event), filename);
  }

  for (const filename of await jsonFiles(invalidDirectory)) {
    const fixture = JSON.parse(await readFile(`${invalidDirectory}/${filename}`, "utf8")) as {
      expectedField: string;
      event: unknown;
    };
    assert.equal(validateSchema(fixture.event), false, `${filename} should fail JSON Schema`);
    assert.throws(
      () => validateEvent(fixture.event),
      (error) =>
        error instanceof EventValidationError && error.field === fixture.expectedField,
      filename,
    );
  }
});

async function jsonFiles(directory: string): Promise<string[]> {
  return (await readdir(directory)).filter((file) => file.endsWith(".json")).sort();
}

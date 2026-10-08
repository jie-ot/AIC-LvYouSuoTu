import { copyFile, readFile, readdir } from "node:fs/promises"
import { join, relative, resolve, sep } from "node:path"
import { pathToFileURL } from "node:url"

/**
 * Next 16's Windows export can keep slashes in RSC segment paths while the
 * browser requests dot-separated names. Preserve the original payloads and
 * add only the missing static aliases, for both Web hosting and Capacitor.
 * Upstream: https://github.com/vercel/next.js/issues/85374
 */
export async function prepareStaticExport(directory) {
  const root = resolve(directory)
  let created = 0
  async function visit(folder) {
    for (const entry of await readdir(folder, { withFileTypes: true })) {
      const source = join(folder, entry.name)
      if (entry.isDirectory()) { await visit(source); continue }
      if (!entry.isFile() || !entry.name.endsWith(".txt")) continue
      const parts = relative(root, source).split(sep)
      const segment = parts.findIndex((part) => part.startsWith("__next."))
      if (segment < 0 || segment === parts.length - 1) continue
      const alias = join(root, ...parts.slice(0, segment), parts.slice(segment).join("."))
      const contents = await readFile(source)
      try {
        const existing = await readFile(alias)
        if (!existing.equals(contents)) throw new Error(`Conflicting static payload: ${relative(root, alias)}`)
      } catch (error) {
        if (error.code !== "ENOENT") throw error
        await copyFile(source, alias)
        created++
      }
    }
  }
  await visit(root)
  return created
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const created = await prepareStaticExport("out")
  console.log(`Static export ready: ${created} RSC path aliases added.`)
}

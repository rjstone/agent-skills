# docshelf trial questions (Node.js 26.3.1, Zig 0.17.1, Pony 0.38.1)

## Node.js 26.3.1
N1 (easy). What does `path.basename('/foo/bar/baz/asdf/quux.html', '.html')` return?
N2 (medium). In Node.js's built-in `node:sqlite`, what are the default values of the `enableForeignKeyConstraints` and `defensive` options of `new DatabaseSync(path, options)`, and in which Node.js versions did `defensive` become enabled by default?
N3 (hard). A Node.js 26 process was started with `--permission --allow-fs-read=*`. Can it call `process.permission.drop('fs.read', '/etc/myapp')` to revoke read access to just that directory? If not, what can it do instead? In which Node.js version was `process.permission.drop()` added?

## Zig 0.17.1
Z1 (easy). What do `@divFloor(-5, 3)` and `@divTrunc(-5, 3)` evaluate to?
Z2 (medium). How do you make a `continue` statement jump to another prong of a `switch` in Zig, and what must such a `continue` include?
Z3 (hard). In Zig 0.17.1, how do you construct the integer type `u18` at comptime from a signedness and a bit width? Give the builtin's exact signature.

## Pony 0.38.1
P1 (easy). In a Pony `Main` actor, how do you print a line to standard output, and what is the declared type (with reference capability) of the field you use?
P2 (medium). In Pony 0.38.1's standard library, what is the declared type of `Env.root`, and why does it have that type?
P3 (hard). Three `Promise[String val]` values p1, p2, p3 are joined with `Promises[String val].join([p1; p2; p3].values())`, then fulfilled in the order p2, p3, p1. In what order do the values appear in the joined array? Also give the full signature of `Promise.next`, including reference capabilities of its parameters and return type.

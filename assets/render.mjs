import sharp from "/tmp/svgrender/node_modules/sharp/lib/index.js";

await sharp("avatar.svg", { density: 300 })
  .resize(1024, 1024)
  .png()
  .toFile("avatar.png");

console.log("done");

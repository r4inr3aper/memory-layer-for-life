// Learn more https://docs.expo.dev/guides/customizing-metro
const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);

// The backend lives in this folder but is not part of the app: it is Python, with its own
// web console and node_modules. Keep Metro from crawling it, which would also leak its
// files into Expo Router's typed routes.
const existing = config.resolver.blockList;
config.resolver.blockList = [
  ...(Array.isArray(existing) ? existing : existing ? [existing] : []),
  /[\\/]memory-layer-for-life[\\/].*/,
];

module.exports = config;

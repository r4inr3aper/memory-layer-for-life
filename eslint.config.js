// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');

module.exports = defineConfig([
  expoConfig,
  {
    // The backend in memory-layer-for-life is a separate Python project.
    ignores: ['dist/*', 'memory-layer-for-life/*', '.expo/*'],
  },
]);

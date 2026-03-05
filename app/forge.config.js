const path = require('path');

module.exports = {
  packagerConfig: {
    name: 'ShellBuddy',
    executableName: 'ShellBuddy',
    appBundleId: 'com.shellbuddy.app',
    asar: {
      unpack: '**/node-pty/**',
    },
    icon: path.join(__dirname, 'assets', 'icon'),
    extraResource: [
      path.join(__dirname, '..', 'scripts'),
      path.join(__dirname, '..', 'backends'),
      path.join(__dirname, '..', 'kb_engine.py'),
      path.join(__dirname, '..', 'kb.json'),
      path.join(__dirname, '..', 'config'),
    ],
    // Uncomment when you have an Apple Developer ID:
    // osxSign: {},
    // osxNotarize: {
    //   appleId: process.env.APPLE_ID,
    //   appleIdPassword: process.env.APPLE_PASSWORD,
    //   teamId: process.env.APPLE_TEAM_ID,
    // },
  },
  rebuildConfig: {},
  makers: [
    {
      name: '@electron-forge/maker-zip',
      platforms: ['darwin'],
    },
    {
      name: '@electron-forge/maker-dmg',
      config: {
        name: 'ShellBuddy',
        format: 'ULFO',
      },
    },
  ],
  plugins: [
    {
      name: '@electron-forge/plugin-auto-unpack-natives',
      config: {},
    },
  ],
};

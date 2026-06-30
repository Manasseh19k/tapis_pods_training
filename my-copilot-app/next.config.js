/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  transpilePackages: [
    "@copilotkit/react-core",
    "@copilotkit/react-ui",
    "@copilotkit/runtime",
  ],
};

module.exports = nextConfig;

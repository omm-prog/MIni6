module.exports = {
  networks: {
    development: {
      host: "127.0.0.1",
      port: 7546,  // Ganache default port
      network_id: "*",
      gas: 6721975 // Any network
    },
  },
  compilers: {
    solc: {
      version: "0.8.19", // Use your Solidity version
    },
  },
};

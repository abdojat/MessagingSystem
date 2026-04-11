module.exports = {
  hooks: {
    readPackage(pkg) {
      if (pkg.name === "orval" && pkg.dependencies) {
        delete pkg.dependencies["@orval/axios"];
      }

      return pkg;
    },
  },
};

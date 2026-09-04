/*
 * Oprava dvoch chyb v image ghcr.io/michaelsp/timelimit-server/timelimit:v1.17.0
 *
 * 1. Povodny build/database/migration/umzug.js hlada migracie globom
 *      "src/database/migration/migrations/*.ts"
 *    lenze v produkcnom image su skompilovane do
 *      "build/database/migration/migrations/*.js"
 *    Glob teda nenajde nic, umzug.up() prebehne naprazdno, schema nikdy
 *    nevznikne a server padne na "Table timelimit.Configs does not exist".
 *
 * 2. Migracie su pisane pre umzug v2 - ocakavaju dva pozicne argumenty
 *      up(queryInterface, sequelize)
 *    ale v image je umzug 3.3.1, ktory vola up({ context, name, path }).
 *    Sequelize tak bolo undefined a migracia padla na
 *    "Cannot read properties of undefined (reading transaction)".
 *    Doplneny resolve() prelozi jedno volanie na druhe.
 *
 * Subor sa do kontajnera len primountuje, image ostava nedotknuty.
 */
"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createUmzug = void 0;
const umzug_1 = require("umzug");
const path_1 = require("path");
const createUmzug = (sequelize) => new umzug_1.Umzug({
    storage: new umzug_1.SequelizeStorage({ sequelize }),
    context: sequelize.getQueryInterface(),
    migrations: {
        glob: "build/database/migration/migrations/*.js",
        resolve: ({ name, path, context }) => {
            const migration = require((0, path_1.resolve)(path));
            return {
                name,
                up: async () => migration.up(context, sequelize),
                down: async () => migration.down(context, sequelize),
            };
        },
    },
    logger: console,
});
exports.createUmzug = createUmzug;

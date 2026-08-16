1. Precheck that only `./data/cache` and `./data/tmp` are selected; do not modify `./data/current`.
2. Reclaim the bounded cache scope first, then the bounded temporary-data scope while preserving an inventory.
3. Verify the supplied block, inode, and deleted-open-file signals improve after each bounded action.
4. Rollback by restoring the recorded cache or temporary-data inventory if a local check fails.

## Status

**Parts of implementation are missing. See the [“MVP” milestone](https://github.com/v6ak/qubes-incremental-backup-poc/issues?q=is%3Aopen+is%3Aissue+milestone%3AMVP) for details. Proof of concept. Backup format details will likely change.**

## Goals

* Incremental backups
* Minimal backup size
* Reasonably exploit-resistant. More specificaly:
    * If filesystem of one VM is maliciously crafted, it does not affect other VMs or their backups, even in case of fs driver bug. And of course, it does not affect dom0 at all.
    * All operations in dom0 are very careful about untrusted inputs, including master config, which is likely to be downloaded from an untrusted place.
* Backup will be transfered over network to some untrusted place.
* Attacker can obtain some reasonably limited metadata about the backup.
* If attacker has modified the backup, it can be detected. Replay attacks (i.e., replacing by some older backup) are not currently intended to be mitigated, though. Attacker that controls the storage can also mix age of backups, remove some VM or add a removed VM.
* bonus: Ability to backup a running VM (if easily achievable)

## How to achieve it

* File-based backup with exclusions of directories like ~/.cache. This allows small backup size and incremental backups.
* Backup is performed of cloned VM images (shapshots on LVM). This allows repairing damaged FS before mounting. It also allows using backup on LVM shapshots while running.
* Backups are both encrypted and authenticated using GPG.
* I just write some scripts that glue some existing software for easy use with Qubes.

## Where to run backup

There are several place where one could run a backup:

* dom0
* Original VM
* One dedicated backup VM
* DVM

The dom0 might sound as an obvious choice, because it has enough access to all data. But this is a wrong way once we need to parse some untrusted filesystem. While dom0 needs to be involved, parsing untrusted filesystem in dom0 is a no-go.

The original VM might also sound as a reasonable choice, because it has access to all the data it needs. There are some minor (though non-negligible) security concerns like VM being able to read and modify its own backups. (This is mostly an issue when handling ransomware, but this is now what I am trying to strongly defend.) But there are also some practical issues. First is non-atomicity of reading the filesystem while the VM is running. For example, when a file is moved during backup, the backup can contain the file twice, once, or it might not contain the file at all. Second practical issue is: Should we shut the VM down after backing up? Maybe we should, because the user does not want it to be running. Maybe we should not, because the user is using the VM. Not shutting all VMs will cause OOM soon on a typical Qubes setup. Shutting all the VMs would close user's work sooner or later. Leaving previous state would be a good heuristic, but still not perfect. Most notably, user can start using a VM while backing up.

Using one dedicated backup VM is no-go for similar reasons to dom0. The VM would be powerful (have plaintext access to content of other VMs) and exposed to attacks from crafted filesystem at the same time.

The remaining option is a DVM, one per VM. This DVM would have access to a clone of filesystem of the relevant VM. If the DVM is compromised through a maliciously crafted filesystem, it does not have access to other VMs. Such exploit would have similar impact as compromised VM that takes care about its own backup. The need of exploiting a bug in filesystem parsing code is a serious mitigation factor, though. This also can allow using the VM when performing backup.

The disadvantage of usage of DVM is that we will probably have to use a different approach for dom0 backups. But dom0 is so special case…

## What software?

I've tried few backup tools. I have decided to use Duplicity. This one was somehow usable and looks to be decently designed:

* Opensource (=> publicly auditable)
* Performs file-based incremental backups (full backup is performed once per a defined interval)
* Backup is encrypted and authenticated using GPG. When one tampers the backup, it should be caught by GPG and the restore procedure should not continue. (I haven't checked if/how they defend against renaming the files or against copying the files under another name. However, such vulnerability would be probably hard to abuse, especially when you cannot cross VMs.)
* Supports various storage backends.
* Writing a custom storage backend seems to be a realistic amount of work: https://github.com/Rudd-O/duplicity-qubes
* GPG can be configured. It can use either symmetric (preferred) or asymmetric cryptography.

I anecdoticaly remember some issues with Duplicity, probably related with interrupted backup process. Maybe we should be careful there, but I don't know a good alternative for Duplicity at the moment.

I haven't performed a deep review of Duplicity.

If you want to use something else, I hope it will not be hard to replace it with some other suitable software. It looks like replacing Duplicity by some other software would require minor (if any) change to the dom0 part.

## Keys for backups

I believe it is clear that we need different keys for different VMs, unless we move the encryption and decryption to dom0. All keys are derived from one passphrase:

    master_key = stretch_key(passphrase)
    subkey_$vm = derive_subkey(master_key, "vm-"+vm)

We also need few other subkeys, but they aren't so important.

Key stretching is intentionally applied only once. Applying it for each VM separately would increase computational cost when running backup for multiple VMs, but it would not make legitimate users more secure against guessing the password. After guessing the password on one VM's backup, attacker would be able to reuse it on other VMs.

Now, we have to define those two functions. Those two functions are meaned as configurable, so one could change them later. (The current implementation might not allow such degree of configurability, though.)

### Key stretching

Why we need this: Key size for encryption is usually enough, but passphrase is usually not as strong. If you use random characters from base64 without padding, you would need to remember 22 characters for equivalent of 128-bit keys or 44 characters for equivalent of 256-bit keys. Moreover, passphrases can be weakened by shouldersurfing. After observing several characters, attacker can try to guess others.

I have picked scrypt, because it is tunable and fairly reviewed. Other functions (like bcrypt) could be also considered there.

Parameters for scrypt are inspired from [https://stackoverflow.com/questions/11126315/what-are-optimal-scrypt-work-factors] . I have considered increasing parallelization parameter, but the implementation of scrypt I have used does not look like being able to use multiple cores. But we still might want to increate p and decrease N in order to lower memory requirements. The link suggests as a more paranoid version something like this:

    stretch_key(passphrase) = scrypt(passphrase, salt, 1<<20, 8, 1, 32)

This requires 1GiB of RAM for scrypt, which is much memory in some cases. Since dom0 can have about 1GiB–4GiB of RAM, depending on requirements of other VMs, it can be a significant portion of total RAM available. I propose decresaing amount of needed memory with similar CPU requirements (similar time without parallelisation, lower memory requirements):

    stretch_key(passphrase) = scrypt(passphrase, salt, 1<<17, 8, 8, 32)

Note that all the parameters are more strict than the soft variant recommended in the post mentioned above. While the recommendation is from 2009, the parameters are increased more than the Moore's inflation as of 2017. (In 8 years, computers are expected to be 2^4 times faster, while this is 2^6 times more hard. Moreover, the Moore's inflation does not hold for some parameters like RAM latency, which can slow the progress down, especially with Scrypt design.)

Another advantage of this approach is that it can be faster for legitimate user when the implementation adds support for parallelism. Note that higher parallelisation does not help attacker when trying large number of passphrases, because it is ambarassimgly parallel task. That is, attacker can use multiple cores even for p=1. Sure, attacker needs fewer memory that with the former parameters. But that's the cost of making it nicer (requiring less memory) for legitimate users. And still, the attacker needs 128MiB of RAM, which is probably enough.

The size 32 \[bytes\] was chosen because we can hardly go (or need to go) beyond 256-bit security.

### Subkeys for VMs

The subkey generation was designed to be fast. Key is already stretched:

    derive_subkey(master_key, subkey_identifier) = hmac(sha256, master_key, subkey_identifier)

I know HMAC was designed for a different purpose. We need a keyed-PRF rather than MAC. But according to https://cseweb.ucsd.edu/~mihir/papers/hmac-new.html, “HMAC is a PRF under the sole assumption that the compression function is a PRF”.

TODO: Is SHA256 really a PRF? I hope so. And it also seems that it is used in such way in TLS: https://crypto.stackexchange.com/questions/26410/whats-the-gcm-sha-256-of-a-tls-protocol

Probably even some punk solution like sha256(master_key || vm_name) would work well (length-extension attack is not practically applicable there), but I would preffer a more standard way.

The sha256 function was chosen because of its output size length. Again, we can hardly go (or need to go) beyond 256-bit security.

## File names

It is tempting to use filenames simply derived from VM name. This would leak some metadata, though. The amount of leaked metadata is not huge, but still noticable. I argue that we should go on the safe side and obscure the metadata in some reasonable way.

We use some kind of deterministic encryption. I have used a scheme similar to AES-SIV (which I have found no suitable implementation for), but I use HMAC-SHA256 instead of S2V. HMAC is simpler, already implemented and should do the same job there. The scheme (I call it AES-HIV) does not support AAD, but this is not a requirement.


## Snapshots

Snapshots are used for VM backup. The type of snapshot depends on the storage type of the VM. Two storage types are supported: plain file and LVM device.

Plain files are simply copied. A check that the VM is not running is performed before the copy process is started. However, when the copy is in progress, the VM can be started, which can lead to some inconsistent copy. Yes, the situation is not nice, but I suppose that file-backed VMs aren't going to be there a long time, because Qubes 4 will reportedly use LVM.

LVM block devices are handled by CoW snapshot. This is much faster and it works in some way even if the VM is running. Well… Actually, if you use a filesystem designed and configured for surviving sudden power outage, it should work well, because the snapshot of mounted filesystem will look like a filesystem where sudden power loss has happened. Practically speaking, if you are using ext4, you should have journal enabled and you shouldn't use flags like data=writeback.

Note that Qubes 3.2 does not officially support LVM for private VM images. It is expected that private.img is a symlink to /dev/*&lt;vg>*/*&lt;lv>*. Other formats like /dev/mapper/*&lt;vg-with-doubled-minuses>*/*&lt;lv-with-doubled-minuses>* are not supported.

## dom0 backup

TODO

## Limitations

* DVM template is somehow trusted.
* We assume that DVM template has drivers for all filesystems we need to backup
* VM config backup is missing. User needs to backup `~/.v6-qubes-backup-poc/master` in order to be able to restore the backup.
* The implementation assumes that attacker cannot read parameters of running applications (e.g., via /proc). This is justifiable in Qubes security model, especially in dom0, but it is not very nice.
* VMs are identified by name. If you destroy a VM and create a VM of the same name then, it will use the same keys and it might have some security implications.
* We strongly assume that attacker does not have any access to dom0. More specificaly, attacker cannot obtain a RAM snapshot of dom0 and attacker cannot list running applications of dom0 (e.g., via /proc). While those assumptions are standard in Qubes security model, failing to satisfy them can cause the backup security to break hardly. No serious attempt has been made to reduce number of copies of sensitive cryptographic material in RAM.
* It assumes that we use locale utf-8. When one switches locale, it can cause issues, mostly with password. If you use another encoding, you might get troubles, especially if your password contains some characters that are represented differently in your encoding than in utf-8.
* It assumes that user does not run the script multiple times in parallel. Various race conditions (cloned images, config files) could happen there.
* (Probably incomplete)

## Human aspects for password

TODO:

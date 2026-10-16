// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {ISignedQuoteSwapAdapter} from "./interfaces/ISignedQuoteSwapAdapter.sol";
import {ITreasuryPilotModule} from "./interfaces/ITreasuryPilotModule.sol";
import {SwapQuoteHash} from "./libraries/SwapQuoteHash.sol";

/// @dev Public getters of the module's storage that the module interface does not list.
interface ISwapModuleState {
    function safeT() external view returns (address);
    function asset() external view returns (address);
    /// @dev 0 = Active, 1 = Paused, 2 = Revoked.
    function status() external view returns (uint8);
}

/// @notice Production swap adapter for `module.swapForGas` (F-065, SC-L03). It is the module's configured
/// "router": Safe T approves exactly `amountIn`, the adapter pulls it, runs a quote-signed route on a
/// governance-allowlisted DEX/aggregator, checks the output against the signed floor, and pays the recipient.
///
/// Trust model: the quote signer decides price and route; governance (Safe T) decides which signers and venues
/// exist; the module still enforces limits, buffer, pause and its own balance-delta checks around every swap.
/// A compromised executor cannot choose a route, price or recipient. A compromised signer is bounded by the
/// module's perRequest/daily swap limits, the pair, the recipient (Safe T) and the TTL.
///
/// The adapter never keeps funds: every swap spends exactly `amountIn` and forwards all output in the same
/// transaction. Stray balances are ignored (balance deltas only) and cannot be taken by a route or a caller.
contract SignedQuoteSwapAdapter is ISignedQuoteSwapAdapter, EIP712, ReentrancyGuard {
    using SafeERC20 for IERC20;

    struct Staged {
        address signer;
        address venue;
        uint64 expiry;
        uint256 minAmountOut;
        bytes32 digest;
        bytes route;
    }

    ITreasuryPilotModule public immutable module;
    /// @notice Safe T of the module. The only taker, recipient and governance address.
    address public immutable governance;
    address public immutable override tokenIn;
    address public immutable override tokenOut;

    uint64 public maxQuoteTtl;
    bool public paused;
    mapping(address signer => bool) public isSigner;
    mapping(address venue => bool) public isVenue;
    mapping(address signer => mapping(uint256 nonce => bool)) public nonceUsed;
    mapping(bytes32 slot => Staged) internal _staged;

    constructor(
        ITreasuryPilotModule module_,
        address tokenOut_,
        uint64 maxQuoteTtl_,
        address[] memory signers,
        address[] memory venues
    ) EIP712("TreasuryPilot Swap Quote", "1") {
        if (address(module_).code.length == 0 || tokenOut_.code.length == 0 || maxQuoteTtl_ == 0) {
            revert InvalidConfiguration();
        }
        ISwapModuleState state = ISwapModuleState(address(module_));
        address tokenIn_ = state.asset();
        if (tokenOut_ == tokenIn_) revert InvalidConfiguration();
        module = module_;
        governance = state.safeT();
        tokenIn = tokenIn_;
        tokenOut = tokenOut_;
        maxQuoteTtl = maxQuoteTtl_;
        for (uint256 i; i < signers.length; ++i) {
            _setSigner(signers[i], true);
        }
        for (uint256 i; i < venues.length; ++i) {
            _setVenue(venues[i], true);
        }
    }

    modifier onlyGovernance() {
        if (msg.sender != governance) revert NotGovernance();
        _;
    }

    // ---------------------------------------------------------------- governance and guardian

    /// @inheritdoc ISignedQuoteSwapAdapter
    function setSigner(address signer, bool allowed) external onlyGovernance {
        _setSigner(signer, allowed);
    }

    /// @inheritdoc ISignedQuoteSwapAdapter
    function setVenue(address venue, bool allowed) external onlyGovernance {
        _setVenue(venue, allowed);
    }

    /// @inheritdoc ISignedQuoteSwapAdapter
    function setMaxQuoteTtl(uint64 maxQuoteTtl_) external onlyGovernance {
        if (maxQuoteTtl_ == 0) revert InvalidConfiguration();
        maxQuoteTtl = maxQuoteTtl_;
        emit MaxQuoteTtlSet(maxQuoteTtl_);
    }

    /// @notice The module guardian or governance can stop the adapter at once. Only governance resumes it.
    function pause() external {
        if (msg.sender != governance && msg.sender != ITreasuryPilotModule(module).mandate().guardian) {
            revert NotGuardianOrGovernance();
        }
        if (!paused) {
            paused = true;
            emit AdapterPaused(msg.sender);
        }
    }

    function resume() external onlyGovernance {
        if (!paused) revert NotPaused();
        paused = false;
        emit AdapterResumed(msg.sender);
    }

    function _setSigner(address signer, bool allowed) internal {
        if (signer == address(0)) revert InvalidConfiguration();
        isSigner[signer] = allowed;
        emit SignerSet(signer, allowed);
    }

    function _setVenue(address venue, bool allowed) internal {
        // A route must never be able to call the tokens or the adapter itself.
        if (venue.code.length == 0 || venue == tokenIn || venue == tokenOut || venue == address(this)) {
            revert InvalidConfiguration();
        }
        isVenue[venue] = allowed;
        emit VenueSet(venue, allowed);
    }

    // ---------------------------------------------------------------- quotes

    /// @inheritdoc ISignedQuoteSwapAdapter
    function domainSeparator() external view returns (bytes32) {
        return _domainSeparatorV4();
    }

    /// @inheritdoc ISignedQuoteSwapAdapter
    function quoteDigest(SwapQuoteHash.SwapQuote calldata quote) public view returns (bytes32) {
        return _hashTypedDataV4(SwapQuoteHash.structHash(quote));
    }

    /// @inheritdoc ISignedQuoteSwapAdapter
    function submitQuote(SwapQuoteHash.SwapQuote calldata quote, bytes calldata route, bytes calldata signature)
        external
        nonReentrant
        returns (bytes32 digest)
    {
        if (paused) revert AdapterIsPaused();
        if (quote.taker != governance) revert WrongTaker();
        if (quote.recipient != quote.taker) revert WrongRecipient();
        if (quote.tokenIn != tokenIn || quote.tokenOut != tokenOut) revert WrongPair();
        if (quote.amountIn == 0 || quote.minAmountOut == 0) revert InvalidAmount();
        if (block.timestamp > quote.expiry) revert QuoteExpired();
        if (quote.expiry - block.timestamp > maxQuoteTtl) revert QuoteTtlTooLong();
        if (!isVenue[quote.venue]) revert VenueNotAllowed();
        if (keccak256(route) != quote.routeHash) revert RouteHashMismatch();
        digest = quoteDigest(quote);
        (address signer, ECDSA.RecoverError err, bytes32 errArg) = ECDSA.tryRecover(digest, signature);
        if (err != ECDSA.RecoverError.NoError || errArg != bytes32(0)) revert BadSignature();
        if (!isSigner[signer]) revert SignerNotAllowed();
        if (nonceUsed[signer][quote.nonce]) revert NonceUsed();
        nonceUsed[signer][quote.nonce] = true;
        _staged[_slot(quote.taker, quote.recipient, quote.amountIn)] =
            Staged(signer, quote.venue, quote.expiry, quote.minAmountOut, digest, route);
        emit QuoteStaged(digest, signer, quote.amountIn, quote.minAmountOut, quote.venue, quote.expiry, quote.nonce);
    }

    /// @notice The staged quote for a swap, or an empty struct.
    function stagedQuote(address taker, address recipient, uint256 amountIn) external view returns (Staged memory) {
        return _staged[_slot(taker, recipient, amountIn)];
    }

    // ---------------------------------------------------------------- swap

    /// @inheritdoc ISignedQuoteSwapAdapter
    function swap(uint256 amountIn, uint256 minOut, address recipient)
        external
        nonReentrant
        returns (uint256 amountOut)
    {
        if (paused) revert AdapterIsPaused();
        if (ISwapModuleState(address(module)).status() != 0) revert ModuleNotActive();
        if (msg.sender != governance) revert NotTaker();
        if (recipient != msg.sender) revert WrongRecipient();
        bytes32 slot = _slot(msg.sender, recipient, amountIn);
        Staged memory q = _staged[slot];
        if (q.signer == address(0)) revert NoStagedQuote();
        // One quote, one swap: delete before any external call.
        delete _staged[slot];
        if (block.timestamp > q.expiry) revert QuoteExpired();
        // Revoking a signer also kills its quotes that are staged but not yet used.
        if (!isSigner[q.signer]) revert SignerNotAllowed();
        if (!isVenue[q.venue]) revert VenueNotAllowed();
        if (minOut < q.minAmountOut) revert QuoteMismatch();

        IERC20 in_ = IERC20(tokenIn);
        IERC20 out_ = IERC20(tokenOut);
        uint256 inBefore = in_.balanceOf(address(this));
        uint256 outBefore = out_.balanceOf(address(this));
        in_.safeTransferFrom(msg.sender, address(this), amountIn);
        if (in_.balanceOf(address(this)) - inBefore != amountIn) revert InputNotSpentExactly();

        in_.forceApprove(q.venue, amountIn);
        // The route is exactly the calldata whose hash the allowlisted signer signed; the venue is allowlisted.
        // slither-disable-next-line low-level-calls
        (bool ok,) = q.venue.call(q.route);
        in_.forceApprove(q.venue, 0);
        if (!ok) revert VenueCallFailed();
        if (in_.balanceOf(address(this)) != inBefore) revert InputNotSpentExactly();

        uint256 outAfter = out_.balanceOf(address(this));
        if (outAfter < outBefore) revert InsufficientOutput();
        amountOut = outAfter - outBefore;
        if (amountOut < minOut || amountOut < q.minAmountOut) revert InsufficientOutput();
        out_.safeTransfer(recipient, amountOut);
        emit QuoteSwapped(q.digest, msg.sender, recipient, amountIn, amountOut);
    }

    function _slot(address taker, address recipient, uint256 amountIn) internal pure returns (bytes32) {
        return keccak256(abi.encode(taker, recipient, amountIn));
    }
}
